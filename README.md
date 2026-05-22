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

## Setting your passphrase

> **There is no "set password" command.** The passphrase is whatever you supply via the `VCLOG_PASS` environment variable on your *first* `save` in a given working directory. Every subsequent `save` or `read` in that directory must use the same passphrase. The skill never stores it.
>
> If you supply a different passphrase later, you will not get an error on `save` (a new block will be appended, sealed with the new key) — but you will then be unable to decrypt either the old or the new blocks consistently. **Use one passphrase per `.versions.log`, forever.**

### How the passphrase is used

1. You set `VCLOG_PASS` in your shell for the duration of one helper command.
2. `vclog.py` runs `scrypt(passphrase, salt-from-.versions.salt)` to derive a 32-byte AES key.
3. That key encrypts (on `save`) or decrypts (on `read`) the block.
4. The shell process exits; `VCLOG_PASS` dies with it.

Nothing about the passphrase touches disk. **There is no recovery.** Lose it → the log is unreadable forever.

### Picking a good passphrase

| Strength | Example | When OK |
|---|---|---|
| Strong (Recommended) | 4–6 random words, e.g. `flax-meridian-obsidian-quartz` | Default. Easy to type, ~50–75 bits entropy. |
| Strong (alt) | 16+ random characters from a password manager | When you'll always copy/paste. |
| Weak | a real word, a date, a name | Never. scrypt slows brute force but doesn't stop it for low-entropy guesses. |

PowerShell one-liner to generate one (uses cryptographic RNG):

```powershell
$words = @('correct','horse','battery','staple','river','stone','plum','axis','copper','quartz','umbra','vellum','ochre','meridian','obsidian','flax','tundra','willow','cobalt','marrow','helix','arcade','vesper','onyx')
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$buf = New-Object byte[] 4
1..4 | ForEach-Object { $rng.GetBytes($buf); $words[[BitConverter]::ToUInt32($buf,0) % $words.Count] } | Join-String -Separator '-'
```

Run it, read the output, write it down somewhere safe (password manager) — **do not paste it back into any chat or commit it to any file.**

### Verify your passphrase works (round-trip test)

Open a fresh terminal — the test runs against a throwaway directory so it can't touch any real `.versions.log`.

**PowerShell:**

```powershell
mkdir $HOME\vctest -Force | Out-Null
Set-Location $HOME\vctest
python "$HOME\.claude\skills\version-control\vclog.py" init

# Read passphrase invisibly — characters won't echo to the screen.
$env:VCLOG_PASS = [System.Net.NetworkCredential]::new("", (Read-Host -AsSecureString "Passphrase")).Password

'hello encrypted world' | python "$HOME\.claude\skills\version-control\vclog.py" save --version 1
python "$HOME\.claude\skills\version-control\vclog.py" read --version 1
# Expect: hello encrypted world

# Clear and clean up
Remove-Item Env:VCLOG_PASS
Set-Location $HOME
Remove-Item -Recurse -Force $HOME\vctest
```

**Bash (macOS / Linux / Git Bash):**

```bash
mkdir -p ~/vctest && cd ~/vctest
python ~/.claude/skills/version-control/vclog.py init

# `read -s` hides input
read -s -p "Passphrase: " VCLOG_PASS; export VCLOG_PASS; echo

echo 'hello encrypted world' | python ~/.claude/skills/version-control/vclog.py save --version 1
python ~/.claude/skills/version-control/vclog.py read --version 1
# Expect: hello encrypted world

unset VCLOG_PASS
cd ~ && rm -rf ~/vctest
```

If `read` prints back the plaintext, your passphrase works. If it prints `decrypt failed — wrong passphrase or block tampered.` (exit 12), you typed it wrong on the second invocation — try the test again.

### Using the passphrase day-to-day

You don't normally set `VCLOG_PASS` yourself. When you ask Claude to *"save version, …"* or *"revert to v3"*, the skill prompts you for the passphrase in chat, scopes it to one helper invocation, and clears it. Set `VCLOG_PASS` manually only when you want to run `vclog.py` directly from your own terminal.

> **Never** pass the passphrase as a CLI flag (e.g. `--passphrase '...'`). The skill deliberately refuses that path — it would expose the passphrase in `ps` listings and shell history.

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
