#!/usr/bin/env bash
# Deploy the app shell (index.html + the city pages it generates + static/)
# to the findacrib.com docroot — and refuse to unless the user journeys pass.
#
#   scripts/deploy_app.sh            # test local -> deploy -> test live
#   scripts/deploy_app.sh --skip-tests   # only when you know why
#
# The journeys (tests/journeys.py) drive the real page as an iPhone and as a
# desktop browser through every visitor path. They run twice: against the
# local index.html before anything is copied, and against the live site after.
# A failure on the live pass prints loudly but does not roll back — fix
# forward and run again. See tests/DEVICE.md for the real-iPhone lane, which
# this script cannot run on its own.
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=root@104.236.120.144
DOC=/var/www/rent-map
PY=${PY:-$HOME/.venvs/dhcr-map/bin/python}
SKIP=${1:-}

if [ "$SKIP" != "--skip-tests" ]; then
  echo "== journeys against the local build"
  "$PY" tests/journeys.py --target local
fi

echo "== regenerating city pages from index.html"
"$PY" build_city_pages.py | tail -1

echo "== deploying"
scp -q index.html "$HOST:$DOC/index.html"
for c in la sf dc westchester; do scp -q "$c/index.html" "$HOST:$DOC/$c/index.html"; done
ssh "$HOST" "mkdir -p $DOC/static/supercluster"
scp -q static/supercluster/supercluster.min.js "$HOST:$DOC/static/supercluster/supercluster.min.js"
for u in / /la/ /sf/ /dc/ /westchester/ /static/supercluster/supercluster.min.js; do
  printf '%-45s %s\n' "$u" "$(curl -s -o /dev/null -w '%{http_code}' "https://findacrib.com$u")"
done

if [ "$SKIP" != "--skip-tests" ]; then
  echo "== journeys against the live site"
  "$PY" tests/journeys.py --target live || echo "!! LIVE JOURNEYS FAILED — the deploy is up; fix forward now"
fi
