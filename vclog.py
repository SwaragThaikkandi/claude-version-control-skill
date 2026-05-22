#!/usr/bin/env python3
"""
vclog.py — encrypted version-control log.

Cipher:    AES-256-GCM (AEAD, 12-byte nonce, 16-byte tag, per-block fresh nonce)
KDF:       scrypt(N=2**15, r=8, p=1) over user passphrase + per-log salt
Layout:    plaintext -> zlib(level=9) -> AES-GCM -> base64 -> one line per version

On-disk files (all in CWD):
    .versions.log    one line per version: "v<N>:<b64nonce>:<b64ct>"
    .versions.idx    one line per version: "v<N>: <log-line> | <iso-ts>"
    .versions.salt   16-byte salt (base64), generated once on init

Passphrase is read from env var VCLOG_PASS (NOT a CLI flag, so it does not
appear in `ps` listings). Set it for one command only:
    VCLOG_PASS='...' python vclog.py save --version 3 < plaintext.txt          # bash
    $env:VCLOG_PASS='...'; python vclog.py save --version 3                    # PowerShell

Subcommands:
    init                          create empty log/idx and a fresh salt
    save  --version N             stdin=plaintext -> append encrypted block, update idx
    read  --version N             decrypt that version's block -> stdout (plaintext)
    list                          print idx as-is
"""

from __future__ import annotations

import argparse
import base64
import datetime as _dt
import os
import sys
import zlib

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
except ImportError:
    sys.stderr.write(
        "missing dependency: install with `pip install cryptography` "
        "(or `py -m pip install cryptography` on Windows).\n"
    )
    sys.exit(3)

SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LEN = 32
NONCE_LEN = 12
SALT_LEN = 16

DEFAULT_LOG = ".versions.log"
DEFAULT_IDX = ".versions.idx"
DEFAULT_SALT = ".versions.salt"


def b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def get_passphrase() -> str:
    p = os.environ.get("VCLOG_PASS")
    if not p:
        sys.stderr.write("set VCLOG_PASS env var with the passphrase.\n")
        sys.exit(4)
    return p


def load_salt(salt_path: str, create: bool = False) -> bytes:
    if os.path.exists(salt_path):
        with open(salt_path, "rb") as f:
            return b64d(f.read().decode("ascii").strip())
    if not create:
        sys.stderr.write(f"salt file {salt_path} missing — run `init` first.\n")
        sys.exit(5)
    salt = os.urandom(SALT_LEN)
    with open(salt_path, "wb") as f:
        f.write(b64e(salt).encode("ascii") + b"\n")
    return salt


def derive_key(passphrase: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=KEY_LEN, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P).derive(
        passphrase.encode("utf-8")
    )


def count_lines(path: str) -> int:
    if not os.path.exists(path):
        return 0
    with open(path, "rb") as f:
        return sum(1 for _ in f)


def find_idx_row(idx_path: str, version: int) -> tuple[int, str]:
    """Return (log_line, timestamp) for version N from the idx file."""
    if not os.path.exists(idx_path):
        sys.stderr.write(f"idx file {idx_path} missing.\n")
        sys.exit(6)
    prefix = f"v{version}:"
    with open(idx_path, "r", encoding="utf-8") as f:
        for row in f:
            if row.startswith(prefix):
                # "v<N>: <log-line> | <iso-ts>"
                _, rest = row.split(":", 1)
                line_part, ts_part = rest.split("|", 1)
                return int(line_part.strip()), ts_part.strip()
    sys.stderr.write(f"version v{version} not found in {idx_path}.\n")
    sys.exit(7)


def read_log_line(log_path: str, line_num: int) -> str:
    with open(log_path, "r", encoding="utf-8") as f:
        for i, row in enumerate(f, start=1):
            if i == line_num:
                return row.rstrip("\n")
    sys.stderr.write(f"line {line_num} not found in {log_path}.\n")
    sys.exit(8)


# ---------------- subcommands ----------------

def cmd_init(args: argparse.Namespace) -> None:
    load_salt(args.salt, create=True)
    for path in (args.log, args.idx):
        if not os.path.exists(path):
            open(path, "a", encoding="utf-8").close()
    sys.stdout.write(f"initialized: {args.log}, {args.idx}, {args.salt}\n")


def cmd_save(args: argparse.Namespace) -> None:
    salt = load_salt(args.salt, create=True)
    key = derive_key(get_passphrase(), salt)
    aes = AESGCM(key)
    nonce = os.urandom(NONCE_LEN)

    plaintext = sys.stdin.buffer.read()
    if not plaintext:
        sys.stderr.write("empty plaintext on stdin — nothing to save.\n")
        sys.exit(9)

    compressed = zlib.compress(plaintext, level=9)
    aad = f"v{args.version}".encode("ascii")
    ct = aes.encrypt(nonce, compressed, aad)

    block = f"v{args.version}:{b64e(nonce)}:{b64e(ct)}\n"
    with open(args.log, "a", encoding="utf-8") as f:
        f.write(block)

    log_line = count_lines(args.log)
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    idx_row = f"v{args.version}: {log_line} | {ts}\n"
    with open(args.idx, "a", encoding="utf-8") as f:
        f.write(idx_row)

    sys.stdout.write(
        f"saved v{args.version} at line {log_line} of {args.log} (ciphertext {len(block)} bytes)\n"
    )


def cmd_read(args: argparse.Namespace) -> None:
    salt = load_salt(args.salt, create=False)
    key = derive_key(get_passphrase(), salt)
    aes = AESGCM(key)

    log_line, _ts = find_idx_row(args.idx, args.version)
    row = read_log_line(args.log, log_line)
    try:
        tag, nonce_b64, ct_b64 = row.split(":", 2)
    except ValueError:
        sys.stderr.write(f"malformed block at line {log_line}.\n")
        sys.exit(10)
    if tag != f"v{args.version}":
        sys.stderr.write(f"block at line {log_line} has tag {tag!r}, expected v{args.version}.\n")
        sys.exit(11)

    nonce = b64d(nonce_b64)
    ct = b64d(ct_b64)
    try:
        compressed = aes.decrypt(nonce, ct, f"v{args.version}".encode("ascii"))
    except Exception:
        sys.stderr.write("decrypt failed — wrong passphrase or block tampered.\n")
        sys.exit(12)
    sys.stdout.buffer.write(zlib.decompress(compressed))


def cmd_list(args: argparse.Namespace) -> None:
    if not os.path.exists(args.idx):
        sys.stdout.write("(no versions yet)\n")
        return
    with open(args.idx, "r", encoding="utf-8") as f:
        sys.stdout.write(f.read())


# ---------------- entrypoint ----------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--log", default=DEFAULT_LOG)
        sp.add_argument("--idx", default=DEFAULT_IDX)
        sp.add_argument("--salt", default=DEFAULT_SALT)

    sp = sub.add_parser("init", help="create empty log/idx and a fresh salt")
    common(sp)

    sp = sub.add_parser("save", help="stdin=plaintext -> append encrypted block")
    common(sp)
    sp.add_argument("--version", type=int, required=True)

    sp = sub.add_parser("read", help="decrypt that version's block -> stdout")
    common(sp)
    sp.add_argument("--version", type=int, required=True)

    sp = sub.add_parser("list", help="print idx as-is")
    common(sp)

    args = p.parse_args()
    {"init": cmd_init, "save": cmd_save, "read": cmd_read, "list": cmd_list}[args.cmd](args)


if __name__ == "__main__":
    main()
