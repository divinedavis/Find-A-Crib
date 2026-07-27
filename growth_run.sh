#!/bin/bash
# Wrapper for the growth engine crons.
#
# The daily review agent runs in Anthropic's cloud with only a git checkout — no
# droplet access. So git IS the channel between it and production: it pushes
# ledger and code changes, and this script pulls them in before each run and
# pushes the night's measurements back out.
set -uo pipefail
cd /root/Find-A-Crib || exit 1
export GROWTH_DOCROOT=/var/www/rent-map
set -a; . ./growth.env; set +a

# Take whatever the review agent pushed. --autostash so uncommitted ledger
# writes from a previous run never block the pull.
git pull --rebase --autostash -q origin main || echo "growth_run: git pull failed, running on the local copy"

python3 growth_daily.py "$@"
rc=$?

# Push the night's measurements back so the next review can read them.
git add -A growth/techniques.json growth/keywords.json growth/results.jsonl growth/journal.md growth/last_run.json 2>/dev/null
if ! git diff --cached --quiet; then
  git commit -q -m "growth: ledger $(date -u +%Y-%m-%d)" && git push -q origin main \
    && echo "growth_run: ledger pushed" || echo "growth_run: ledger push FAILED"
fi
exit $rc
