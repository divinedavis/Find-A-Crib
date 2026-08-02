#!/bin/bash
# Daily re-rental sweep: one browser pass that updates the public page AND
# mails the digest. Replaces the weekly check_rerentals.sh cron — that script
# is still useful by hand, but running both would sweep the same 14 sites twice.
#
# Deliberately NOT set -e: one unreachable agent site must not stop the run.
# rerental_daily.py keeps the previous state for anything it couldn't load.
set -uo pipefail
cd /root/Find-A-Crib || exit 1
export GROWTH_DOCROOT=${GROWTH_DOCROOT:-/var/www/rent-map}
if [ -f ./growth.env ]; then set -a; . ./growth.env; set +a; fi

git pull --rebase --autostash -q origin main \
  || echo "rerental_daily: git pull failed, running on the local copy"

# Playwright lives in the scraper's venv, not the system python.
PY=/var/www/rent-map/venv/bin/python
[ -x "$PY" ] || PY=python3
"$PY" -c 'import playwright' 2>/dev/null || {
  echo "rerental_daily: no playwright in $PY"; exit 1; }

"$PY" rerental_daily.py --update-site --out "$GROWTH_DOCROOT" "$@"
rc=$?

# Same 14 sites, second pass: pull a full record per apartment (rent, units,
# photo, apply link) for the featured tiles in the map grid. It is a separate
# pass because the digest above only needs a key per listing and this needs the
# whole card — but it rides this cron so the sites are only visited once a day
# in total, and a failure here must not fail the digest.
"$PY" featured_rerentals.py --apply --out "$GROWTH_DOCROOT" \
  || echo "rerental_daily: featured tiles FAILED (digest above is unaffected)"

git add -A rerental_pages.json marketing_agents.json featured.json 2>/dev/null
if ! git diff --cached --quiet; then
  git commit -q -m "re-rentals: daily sweep $(date -u +%Y-%m-%d)" \
    && git push -q origin main \
    && echo "rerental_daily: state pushed" \
    || echo "rerental_daily: push FAILED"
fi
exit $rc
