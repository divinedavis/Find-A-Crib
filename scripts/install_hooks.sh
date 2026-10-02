#!/usr/bin/env bash
# Point git at the versioned hooks in .githooks/ (pre-push: gitleaks + unit
# tests). Run once per checkout — including worktrees and the droplet's.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
echo "hooks installed: $(ls .githooks | tr '\n' ' ')"
