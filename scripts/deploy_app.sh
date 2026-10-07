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
# The unit tests (tests/run_unit.py) run first. Before the copy, the files
# about to be replaced are snapshotted on the box under $BACKUPS; if the live
# pass fails, the failed journeys get one re-run (live has real network
# flake), and anything still failing rolls the docroot back to that snapshot
# and exits 1. scripts/rollback_app.sh restores any snapshot by hand. See
# tests/DEVICE.md for the real-iPhone lane, which this script cannot run.
#
# What this script does NOT deploy, and where those pages go instead:
# /developers/, /embed/ and /marketing-agents/ are hand-authored HTML that was
# never on the scp list below and had no deploy path anywhere until
# 2026-09-13. They now ride the nightly SEO rsync — build_seo.py's
# stage_static_pages() copies them into $BUILD/seo and scripts/refresh_seo.sh
# rsyncs that into the docroot. Do not add them here as well; one deploy path
# per file, and the nightly one is the one that runs without a human.
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=root@142.93.183.172
DOC=/var/www/rent-map
PY=${PY:-$HOME/.venvs/dhcr-map/bin/python}
SKIP=${1:-}
BACKUPS=/var/backups/findacrib-app
# Everything the copy below replaces, relative to $DOC. Keep in step with it.
SHIPPED="index.html la/index.html sf/index.html dc/index.html westchester/index.html static/supercluster/supercluster.min.js static/mapillary-preview.js static/apple-street-preview.js static/apple-street-frame.html"

if [ "$SKIP" != "--skip-tests" ]; then
  echo "== unit tests"
  "$PY" tests/run_unit.py 2>/dev/null
fi

echo "== regenerating city pages from index.html"
"$PY" build_city_pages.py | tail -1

if [ "$SKIP" != "--skip-tests" ]; then
  "$PY" tests/apple_street_preview.py
  "$PY" tests/street_view.py
  echo "== journeys against the local build"
  # One re-run for a journey that fails, as the live pass already does: four
  # deploys on 2026-10-03 stopped on a different one-off flake each time
  # (WebKit NotReadableError, a profile modal 1.5 s late, a QR read in dark
  # mode, the Mac's network dropping), every one passing 3/3 when re-run.
  # A journey that fails twice still stops the deploy.
  LFAILED=$(mktemp)
  if ! "$PY" tests/journeys.py --target local --failed-out "$LFAILED"; then
    echo "== re-running the failed local journeys once: $(tr '\n' ' ' <"$LFAILED")"
    while read -r name; do
      "$PY" tests/journeys.py --target local --only "$name" || { echo "!! $name failed twice on the local build"; exit 1; }
    done <"$LFAILED"
  fi
fi

echo "== snapshotting what is live now"
SNAP=$(date -u +%Y%m%dT%H%M%SZ)
ssh "$HOST" "set -e; mkdir -p $BACKUPS/$SNAP; cd $DOC
  for f in $SHIPPED; do [ -f \$f ] && install -D -m 644 \$f $BACKUPS/$SNAP/\$f; done
  ls -1d $BACKUPS/*/ | head -n -15 | xargs -r rm -rf"
echo "   $BACKUPS/$SNAP (scripts/rollback_app.sh $SNAP)"

echo "== deploying"
ssh "$HOST" "mkdir -p $DOC/static/supercluster"
scp -q static/supercluster/supercluster.min.js "$HOST:$DOC/static/supercluster/supercluster.min.js"
scp -q static/mapillary-preview.js static/apple-street-preview.js static/apple-street-frame.html "$HOST:$DOC/static/"
scp -q index.html "$HOST:$DOC/index.html"
for c in la sf dc westchester; do scp -q "$c/index.html" "$HOST:$DOC/$c/index.html"; done
for u in / /la/ /sf/ /dc/ /westchester/ /static/supercluster/supercluster.min.js; do
  printf '%-45s %s\n' "$u" "$(curl -s -o /dev/null -w '%{http_code}' "https://findacrib.com$u")"
done
scripts/check_docroot_leaks.sh

if [ "$SKIP" != "--skip-tests" ]; then
  echo "== journeys against the live site"
  FAILED=$(mktemp)
  if ! "$PY" tests/journeys.py --target live --failed-out "$FAILED"; then
    echo "== re-running the failed journeys once: $(tr '\n' ' ' <"$FAILED")"
    STILL=0
    while read -r name; do
      "$PY" tests/journeys.py --target live --only "$name" || STILL=1
    done <"$FAILED"
    if [ "$STILL" = 1 ]; then
      echo "!! live journeys still failing — rolling back to $SNAP"
      scripts/rollback_app.sh "$SNAP"
      exit 1
    fi
  fi
  rm -f "$FAILED"
fi
