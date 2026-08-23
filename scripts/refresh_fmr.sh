#!/usr/bin/env bash
# Rebuild fmr.json and ship it to the droplet — from this Mac, not from the box.
#
# HUD's WAF blocks the droplet: huduser.gov answers a datacenter IP with HTTP 202
# and an empty body, so build_fmr.py cannot run there (it fails in openpyxl with
# BadZipFile, which is what an HTML challenge page looks like to a zip reader).
# It fetches fine from a residential connection, so the build runs here and only
# the result crosses. Scheduled by com.divinedavis.findacrib-fmr.plist.
#
# The server-side alternative is HUD's API (huduser.gov/hudapi/public/fmr), which
# needs a free bearer token; it answers 401 without one. Worth switching to if
# this ever needs to run unattended on the box.
#
# Body in a function for the same reason as refresh_hpd.sh: bash reads a script
# incrementally and this one pulls itself.
set -euo pipefail

REPO="$HOME/projects/dhcr-map"
HOST="${FAC_HOST:-root@104.236.120.144}"

main() {
  cd "$REPO"
  git pull -q --ff-only || echo "  ! git pull failed; running the checked-out version"

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] FMR refresh starting"
  python3 build_fmr.py

  # Ship only on a real change. HUD publishes once a year, so eleven of twelve
  # runs should print "unchanged" — and a diff in a month that is not October is
  # worth seeing in the log rather than silently deploying.
  if curl -fsS -m 30 https://findacrib.com/fmr.json -o /tmp/fmr.live.json 2>/dev/null \
     && cmp -s fmr.json /tmp/fmr.live.json; then
    echo "  fmr.json unchanged; nothing shipped"
  else
    scp -q fmr.json "$HOST:/var/www/rent-map/fmr.json"
    ssh "$HOST" "chown www-data:www-data /var/www/rent-map/fmr.json"
    echo "  shipped a changed fmr.json"
  fi
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] FMR refresh complete"
}

main "$@"
