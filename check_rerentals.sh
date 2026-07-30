#!/bin/bash
# Weekly re-verification of the agents' re-rental pages.
#
# Same shape as growth_run.sh: git is the channel, so pull before and push
# after. rerental_pages.json is state the droplet writes and a human reads, so
# it has to get back into the repo or the next laptop-side edit clobbers it.
#
# Deliberately NOT set -e: a single unreachable agent site must not stop the
# run. check_rerentals.py keeps the previous units_seen for anything it
# couldn't load, so a flaky week degrades to "stale", never to "wrong".
set -uo pipefail
cd /root/Find-A-Crib || exit 1
export GROWTH_DOCROOT=${GROWTH_DOCROOT:-/var/www/rent-map}
# SMTP_* for the change email. Same file the growth engine sources.
if [ -f ./growth.env ]; then set -a; . ./growth.env; set +a; fi

git pull --rebase --autostash -q origin main \
  || echo "check_rerentals: git pull failed, running on the local copy"

# Playwright lives in the scraper's venv, not in the system python. Prefer it,
# and say so loudly rather than dying with a bare ModuleNotFoundError in a log.
PY=/var/www/rent-map/venv/bin/python
[ -x "$PY" ] || PY=python3
"$PY" -c 'import playwright' 2>/dev/null || {
  echo "check_rerentals: no playwright in $PY — install it or point PY at the venv"; exit 1; }

"$PY" check_rerentals.py --apply --out "$GROWTH_DOCROOT" "$@"
rc=$?

git add -A rerental_pages.json marketing_agents.json 2>/dev/null
if ! git diff --cached --quiet; then
  git commit -q -m "re-rentals: weekly check $(date -u +%Y-%m-%d)" \
    && git push -q origin main \
    && echo "check_rerentals: state pushed" \
    || echo "check_rerentals: push FAILED"
fi
exit $rc
