# install.ps1 — copy the skill into ~/.claude/skills/version-control/
# Usage:  ./install.ps1
$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $HOME ".claude\skills\version-control"

New-Item -ItemType Directory -Force -Path $target | Out-Null

Copy-Item -Path (Join-Path $here "SKILL.md") -Destination $target -Force
Copy-Item -Path (Join-Path $here "vclog.py") -Destination $target -Force

Write-Output "Installed skill to $target"
Write-Output ""
Write-Output "Dependency check: cryptography"
try {
    $v = & py -c "import cryptography; print(cryptography.__version__)" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Output "  cryptography $v detected — OK"
    } else {
        throw "py exited non-zero"
    }
} catch {
    Write-Output "  cryptography NOT found. Install with:  py -m pip install cryptography"
}
