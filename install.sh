#!/usr/bin/env bash
# install.sh — copy the skill into ~/.claude/skills/version-control/
# Usage:  ./install.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
target="${HOME}/.claude/skills/version-control"

mkdir -p "$target"
cp -f "${here}/SKILL.md" "$target/"
cp -f "${here}/vclog.py" "$target/"

echo "Installed skill to $target"
echo
echo "Dependency check: cryptography"
if python3 -c "import cryptography, sys; print(cryptography.__version__)" 2>/dev/null; then
    echo "  cryptography detected — OK"
else
    echo "  cryptography NOT found. Install with:  pip install cryptography"
fi
