---
name: version-control
description: Lightweight per-project version control with an AEAD-encrypted change log. Use when the user says "save version", "snapshot", "checkpoint", "track this change", "list versions", "revert to vN", "undo to version N", "reverse vN", or invokes `/version-control`. Each version is one encrypted line in `.versions.log` (AES-256-GCM + scrypt KDF), indexed in `.versions.idx`. Decryption requires a user passphrase the assistant prompts for and never persists. Produces a new reverted file on demand without overwriting the original.
---

# version-control skill

Lightweight local versioning. Not git. One encrypted log per working directory holds all versions as AEAD-sealed blocks (one line per version). A plaintext index maps each version number to its line in the log so reads slice instead of scan. Decryption happens inside a Python helper invoked via shell — **the ciphertext never enters the assistant's context**, so a 100-version log costs only the tokens of the one version being read.

## Files (all in CWD)

| File | Contents | Sensitivity |
|------|----------|-------------|
| `.versions.log` | One AEAD-encrypted block per line: `v<N>:<b64nonce>:<b64ciphertext>`. zlib-compressed plaintext sealed with AES-256-GCM. | Encrypted; safe at rest against casual snooping. |
| `.versions.idx` | One row per version: `v<N>: <log-line-number> | <iso-timestamp>`. **Plaintext, metadata-only — no summaries, no paths, no diff content.** | Reveals only version count and timestamps. |
| `.versions.salt` | Per-log random 16-byte scrypt salt, base64. Generated on first save. | Public (useless without passphrase). |

The skill never deletes from `.versions.log`. Append-only. Reverts produce new files.

## Helper script

`vclog.py` lives next to this `SKILL.md` (at `~/.claude/skills/version-control/vclog.py`). Subcommands:

| Command | Effect |
|---------|--------|
| `init` | Create empty log/idx + fresh salt. Idempotent. |
| `save --version N` | Read plaintext from stdin → zlib → AES-256-GCM (AAD bound to `v<N>`) → base64 → append one line to log + one row to idx. |
| `read --version N` | Look up version's log line in idx, decrypt, write plaintext to stdout. |
| `list` | Print idx as-is. |

Defaults to `.versions.log` / `.versions.idx` / `.versions.salt`; overridable with `--log` / `--idx` / `--salt`.

**Passphrase is supplied via the `VCLOG_PASS` environment variable** — never as a CLI flag (would show up in `ps`). Set it for one command and unset right after.

### Dependency

Requires the `cryptography` Python package (KDF + AEAD primitives). If `vclog.py` exits with code 3, run `py -m pip install cryptography` (Windows) or `pip install cryptography` and retry. Do not substitute another library without the user's say-so.

## Workflow — passphrase handling (CRITICAL)

Every time this skill is invoked:

1. Ask the user for the passphrase: *"Passphrase for the version log? (won't be stored anywhere)"*.
2. Keep it only in the current Bash environment, scoped to each command:
   - **PowerShell (default on this user's machine):** `$env:VCLOG_PASS = '<pass>'; python ... ; Remove-Item Env:VCLOG_PASS`
   - **Bash:** `VCLOG_PASS='<pass>' python ...` (env var dies with the process — no explicit unset needed).
3. **Never write the passphrase to any file, memory entry, log, or response.** Do not echo it back. If the user pastes it visibly, do not repeat it.
4. If decryption fails (`exit code 12`), report "wrong passphrase or tampered block" — do not retry guessing.

## Block plaintext format (inside the encrypted blob)

Each version's plaintext (before zlib + encryption) is:

```
=== BEGIN v<N> ===
TIME: <ISO-8601 UTC>
TARGET: <relative path of file OR "PROJECT" for multi-file>
SUMMARY: <one-line forward description>
FORWARD_PROMPT: <imperative NL: how to re-apply this change to the prior state>
REVERSE_PROMPT: <imperative NL: how to undo this change from the current state>
FORWARD:
  <op>
  <op>
  ...
REVERSE:
  <op>
  <op>
  ...
=== END v<N> ===
```

Both compressed mechanical ops AND short NL prompts are stored so the undo can be applied either deterministically (ops, default) or via LLM re-edit (prompts, fallback when ops drift).

### Op notation (one op per line, two-space indent)

| Op | Meaning |
|----|---------|
| `+<line>: <content>` | Insert `<content>` at line `<line>` (1-indexed, post-insert position) |
| `-<line>: <content>` | Delete line `<line>` whose contents were `<content>` |
| `~<line>: <old> >> <new>` | Replace line `<line>` content `<old>` with `<new>` |
| `F+ <path>` | Created file at `<path>` (REVERSE pair: `F- <path>`) |
| `F- <path>` | Deleted file at `<path>` (REVERSE pair: `F+ <path>` with restored content as `+` ops below) |
| `R <old> >> <new>` | Renamed file (REVERSE swaps) |

Multi-file change: precede each file's ops with `FILE: <path>` line.

Compression rules to keep blocks small:
- Trim trailing whitespace. Replace tabs with `\t` and embedded newlines with `\n` so every op stays on one line.
- For contiguous runs > 5 lines, use range form `+<start>-<end>:` followed by indented content lines ending with `.` alone.
- If a single file change exceeds ~200 ops, instead store a full snapshot of the resulting state inside FORWARD as `SNAPSHOT: <b64(zlib(content))>` (and the prior snapshot in REVERSE), then the line ops become unnecessary for that file.

## Modes

### 1. SAVE — record a new version

Inputs needed (ask only if not already clear from context): target file or `PROJECT`, one-line summary. If user already described the change in the conversation, reuse it as the summary — don't re-ask. Ask for the passphrase if not already obtained in this skill invocation.

Steps:
1. If `.versions.salt` doesn't exist: `python ~/.claude/skills/version-control/vclog.py init` (creates all three files).
2. Determine `N = (count of rows in .versions.idx) + 1`. (Read the idx; it stays small.)
3. Read the current state of the target file(s).
4. Determine the prior state:
   - First version: prior state = empty (or current — record `SUMMARY: initial` with empty ops).
   - Otherwise: replay all FORWARD ops from v1..v(N-1) against an empty buffer (or start from the most recent block that stores `SNAPSHOT:`). To get each prior block's plaintext: `python vclog.py read --version K` (one call per version), discard ciphertext.
5. Compute minimal diff prior→current → FORWARD ops + inverse REVERSE ops + short NL FORWARD_PROMPT and REVERSE_PROMPT (≤200 chars each, no newlines).
6. Build the block plaintext (text shown above).
7. Pipe to the helper:
   - **PowerShell:**
     ```powershell
     $env:VCLOG_PASS = '<pass>'
     $plain = @'
     === BEGIN v<N> ===
     ...
     === END v<N> ===
     '@
     $plain | python ~/.claude/skills/version-control/vclog.py save --version <N>
     Remove-Item Env:VCLOG_PASS
     ```
   - **Bash:**
     ```bash
     VCLOG_PASS='<pass>' python ~/.claude/skills/version-control/vclog.py save --version <N> <<'EOF'
     === BEGIN v<N> ===
     ...
     === END v<N> ===
     EOF
     ```
8. Report to the user: `Saved v<N> at line <L> of .versions.log. Summary: <…>`.

**Token-efficiency rule:** never `cat` or otherwise dump `.versions.log` into the conversation. The only legitimate way to inspect log contents is via `vclog.py read --version N`, which returns only the requested block as plaintext.

### 2. LIST — show available versions

Run `python ~/.claude/skills/version-control/vclog.py list` and print the result. Summaries are encrypted inside the log, so the bare list only shows `v<N> | timestamp`. If the user wants summaries too, decrypt each block (`vclog.py read --version N`) and print the SUMMARY line — note this requires the passphrase.

### 3. REVERT — produce a reversed file (never overwrite)

User asks "revert to v<K>" (meaning: undo all versions after v<K>, leaving file at v<K>'s resulting state) or "reverse v<N>" (undo just v<N>).

CRITICAL: **never overwrite the working file.** Write to a new file:
- Single file: `<basename>.rev_v<K>.<ext>` (append `.rev_v<K>` if no extension).
- Multi-file `PROJECT` revert: directory `revert_v<K>/` mirroring the project layout.

Steps:
1. Look up affected versions in idx (`vclog.py list`).
2. For each version being undone (latest first), `vclog.py read --version N` → parse REVERSE ops.
3. Read the current working file into a buffer.
4. Apply REVERSE ops in reverse-chronological order to the buffer.
5. If any op fails to apply cleanly (line numbers drifted because the file was hand-edited outside the skill, or the block stores only `SNAPSHOT:`), fall back: re-read the current file and follow that version's `REVERSE_PROMPT` as an LLM-driven edit. Note in the report which versions used the prompt-fallback path so the user can sanity-check.
6. Write the buffer to the new revert file. Do NOT modify the original.
7. Report: new file path, which versions were undone, which used prompt fallback.

If the user later wants to accept the revert ("apply the revert", "make it official"), only then overwrite the original, **and immediately SAVE a new forward version** recording the revert itself — so the revert is reversible too.

## Worked example

User edits `src/foo.py` to add a logging import and a log call inside `bar()`, then says "save version, added logging to bar()".

The skill asks once for the passphrase (e.g. `cdmrl-2026`), then:
1. Reads `src/foo.py`, computes prior state (empty for v1), builds FORWARD / REVERSE ops + NL prompts.
2. Composes the plaintext block.
3. Runs (PowerShell):
   ```powershell
   $env:VCLOG_PASS = 'cdmrl-2026'
   $plain | python ~/.claude/skills/version-control/vclog.py save --version 1
   Remove-Item Env:VCLOG_PASS
   ```
4. Helper writes one line to `.versions.log` (e.g. 229 bytes for this small change) and one row to `.versions.idx`:
   ```
   v1: 1 | 2026-05-22T11:43:59Z
   ```

Later, "revert to v0":
1. `vclog.py read --version 1` → plaintext block (only this block enters context).
2. Parse REVERSE ops, apply to current `src/foo.py` in memory.
3. Write result to `src/foo.rev_v0.py`. Original `src/foo.py` untouched.
4. Report the new file path.

## Security caveats (tell the user once, on first use this session)

- The cipher (AES-256-GCM) and KDF (scrypt, N=2^15) are standard and strong. Strength is bounded by the **passphrase**: a short or common passphrase is brute-forceable regardless of the cipher. Use at least 4 random words or ~16 random characters.
- AAD binds each ciphertext to its version number, so blocks cannot be reordered or swapped without detection.
- The `.versions.idx` and `.versions.salt` files are intentionally plaintext. They leak the version count, timestamps, and the salt — nothing else. Do not store the passphrase anywhere near them.
- Lines flagged as containing secrets (API keys, tokens, passwords) by simple pattern recognition should still be `<REDACTED>` in the stored ops, even though the block is encrypted — defense in depth.

## Implementation notes for the assistant

- Use the Read tool for source files. Use Bash (or PowerShell) only to invoke `vclog.py`. Do not Read `.versions.log` — it adds ciphertext to context, defeating the token-efficiency goal.
- Line numbers inside ops refer to the file being changed. Line numbers in `.versions.idx` refer to `.versions.log`. Do not conflate.
- When generating ops, apply them in listed order against the prior state to produce the new state and confirm the inverse REVERSE ops reproduce the prior state from the new state. If a quick mental simulation doesn't match, the diff is wrong — recompute before saving.
- Set `$env:VCLOG_PASS` only for the duration of one helper invocation, then `Remove-Item Env:VCLOG_PASS` (PowerShell) or rely on inline `VAR=...` scoping (Bash). Never echo the passphrase back.
- If `vclog.py` exits 3 (missing `cryptography`), tell the user the exact install command for their shell and stop until they confirm it's installed.
- If `.versions.idx` and `.versions.log` disagree (idx row points outside the log, or block tag mismatches version), report the inconsistency to the user and do not attempt automatic repair — the divergence may indicate tampering.
