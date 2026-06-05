#!/usr/bin/env bash
#
# git-pull-ff-safe-pattern.sh
#
# Sicheres "git pull" mit Fast-Forward only.
# Stop-Kriterium: bricht bei dirty worktree oder nicht möglichem FF ab.
#
# Quelle: /home/alex/repos/steuerboard
# Siehe auch: docs/git-pull-ff-only-contract.md

set -euo pipefail

REPO="${1:-/home/alex/repos/steuerboard}"

cd "$REPO"

echo "== Vorher =="
git status --short
git branch --show-current
git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || echo "WARN: kein Upstream gesetzt"

echo
echo "== Fetch =="
git fetch --prune

echo
echo "== Vergleich lokal/upstream =="
git status -sb

echo
echo "== Pull fast-forward only =="
git pull --ff-only

echo
echo "== Nachher =="
git status -sb
git log --oneline -5