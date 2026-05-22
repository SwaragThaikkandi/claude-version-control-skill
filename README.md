# claude-version-control-skill

A lightweight, **encrypted** per-project version control [skill](https://docs.claude.com/en/docs/agents-and-tools/claude-code/skills) for Claude Code. Not a replacement for git — a complementary checkpoint system that fits inside one (or a few) files, with strong encryption and zero token cost for unused versions.

## What it does

- **Save versions** — when you say *"save version, added logging to bar()"*, Claude diffs your file, produces compressed forward + reverse operations plus short natural-language prompts, and appends one encrypted line to `.versions.log`.
- **List versions** — Claude reads `.versions.idx` (plaintext metadata only) and prints version numbers + timestamps.
- **Revert** — when you say *"revert to v3"* or *"reverse v5"*, Claude decrypts the relevant block(s), applies the REVERSE operations to the current file, and writes the result to a **new** file (e.g. `foo.rev_v3.py`). Your working file is never overwritten.

## Why encrypted

Anyone with read access to `.versions.log` would otherwise have a perfect diff of every change you've made — which can leak intent, secrets, or in-progress work. This skill seals every block with AES-256-GCM keyed by a passphrase only you know.

| Layer | Choice | Why |
|-------|--------|-----|
| Compression | zlib(level=9) before encryption | Encryption destroys redundancy; compress first. ~3× shrink on text. |
| Cipher | AES-256-GCM (AEAD) | Confidentiality + integrity. 12-byte nonce, 16-byte tag, AAD bound to version number → blocks can't be reordered. |
| KDF | scrypt N=2^15, r=8, p=1 | Memory-hard, GPU-resistant. Standard. |
| Encoding | base64 | ~33% overhead. ~2.3× smaller than 3-digit-decimal alternatives. |
| Storage | one block per line in `.versions.log` | O(1) slicing via line number index. |
| Token cost | **Ciphertext never enters Claude's context** | Decryption happens in a Python helper called via Bash; only the requested block's plaintext is returned. Reading v1 from a 100-version log costs the same tokens as reading from a 1-version log. |

## Files this skill creates in your working directory

| File | Contents | Sensitivity |
|------|----------|-------------|
| `.versions.log` | One AEAD-encrypted block per line: `v<N>:<b64nonce>:<b64ciphertext>` | Encrypted. Safe at rest against casual snooping. |
| `.versions.idx` | One row per version: `v<N>: <log-line> | <iso-timestamp>` | **Plaintext, metadata-only.** Reveals only version count and timestamps — no paths, no summaries, no diff content. |
| `.versions.salt` | 16-byte scrypt salt, base64. Generated once. | Public (useless without passphrase). |

None of these contain your source code — they live alongside it and reference it.

## Install

### 1. Install the Python dependency

```bash
py -m pip install cryptography   # Windows
pip install cryptography         # macOS / Linux
```

### 2. Install the skill into Claude Code

Clone this repo and run the installer for your shell:

```powershell
# Windows / PowerShell
git clone https://github.com/SwaragThaikkandi/claude-version-control-skill.git
cd claude-version-control-skill
./install.ps1
```

```bash
# macOS / Linux
git clone https://github.com/SwaragThaikkandi/claude-version-control-skill.git
cd claude-version-control-skill
./install.sh
```

The installer copies `SKILL.md` and `vclog.py` to `~/.claude/skills/version-control/`. Claude Code auto-discovers skills from that directory.

### 3. Verify

```bash
mkdir vctest && cd vctest
python ~/.claude/skills/version-control/vclog.py init
VCLOG_PASS='your-passphrase' python ~/.claude/skills/version-control/vclog.py save --version 1 <<< 'hello world'
VCLOG_PASS='your-passphrase' python ~/.claude/skills/version-control/vclog.py read --version 1
# -> hello world
VCLOG_PASS='wrong-pass'      python ~/.claude/skills/version-control/vclog.py read --version 1
# -> decrypt failed — wrong passphrase or block tampered.   (exit 12)
```

(PowerShell uses `$env:VCLOG_PASS = '...'; python ... ; Remove-Item Env:VCLOG_PASS` instead of inline `VAR=` prefix.)

## Usage with Claude Code

Once installed, in any project:

- *"save version, added retry logic to fetcher"* → Claude asks for your passphrase, diffs the file, appends an encrypted block.
- *"list versions"* → Claude prints `.versions.idx`.
- *"revert to v3"* → Claude asks for passphrase, decrypts blocks v4..vN, applies REVERSE ops to current file, writes the reverted state to a new file. **The original file is never touched without your explicit say-so.**

The passphrase is requested fresh each session, kept only in the Bash environment for the duration of one helper call, and never written to disk, memory files, or chat history.

## Security notes

- Strength is bounded by your passphrase. Use at least 4 random words (~50 bits entropy) or 16+ random characters.
- `.versions.idx` and `.versions.salt` are intentionally plaintext. They leak version count, timestamps, and the random salt — nothing more.
- AAD binds each ciphertext to its version number → blocks cannot be reordered or swapped without detection.
- Lines that look like secrets (API keys, tokens, passwords) should be `<REDACTED>` in stored ops, even though the block is encrypted — defense in depth.
- **There is no passphrase recovery.** Lose the passphrase and the log is permanently undecryptable.

## How it differs from git

| | git | this skill |
|---|---|---|
| Scope | Project-wide | Per-file or per-project, lightweight |
| Network | Local + remote | Local only |
| Encryption | None at rest | AES-256-GCM at rest |
| Token cost to assistant | High (whole diffs) | ~zero for unused versions |
| Granularity | Per commit | Per save invocation |
| Use case | Source-of-truth versioning | Quick checkpoints / experimental edits / contexts where committing would be churn |

Use both. They don't fight.

## License

MIT — see [LICENSE](LICENSE).
