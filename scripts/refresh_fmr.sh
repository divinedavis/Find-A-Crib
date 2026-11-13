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
HOST="${FAC_HOST:-root@142.93.183.172}"

main() {
  cd "$REPO"
  git pull -q --ff-only || echo "  ! git pull failed; running the checked-out version"

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] FMR refresh starting"
  # The project venv: system python3 has no openpyxl, so every monthly run
  # failed at import (found 2026-10-24, logs in /tmp long gone).
  #
  # That WAS written off as "harmless only because HUD hadn't posted FY2027
  # yet". It is not harmless any more and the premise has expired: the federal
  # FY2027 FMRs took effect 2026-10-01, so every month this silently failed
  # after that date left the site serving a prior year's figures. Whether it
  # actually is doing so is exactly what fmr.meta.json now records — a run of
  # this script is what answers it.
  "${PY:-$HOME/.venvs/dhcr-map/bin/python}" pipeline/build_fmr.py

  # Ship only on a real change. HUD publishes once a year, so eleven of twelve
  # runs should print "unchanged" — and a diff in a month that is not October is
  # worth seeing in the log rather than silently deploying.
  if curl -fsS -m 30 https://findacrib.com/fmr.json -o /tmp/fmr.live.json 2>/dev/null \
     && cmp -s data/fmr.json /tmp/fmr.live.json; then
    echo "  fmr.json unchanged; nothing shipped"
  else
    scp -q data/fmr.json "$HOST:/var/www/rent-map/fmr.json"
    ssh "$HOST" "chown www-data:www-data /var/www/rent-map/fmr.json"
    echo "  shipped a changed fmr.json"
  fi

  # fmr.meta.json ships UNCONDITIONALLY, unlike fmr.json above. It is ~200
  # bytes, its "built" stamp changes on every successful run by design, and its
  # whole job is to say which fiscal year the figures beside it are — a docroot
  # holding this year's fmr.json next to a missing or last-year's meta is the
  # one state that would make the site label its rents wrongly. Shipping it
  # every time keeps the pair in lockstep for the cost of one scp.
  if [ -f data/fmr.meta.json ]; then
    scp -q data/fmr.meta.json "$HOST:/var/www/rent-map/fmr.meta.json"
    ssh "$HOST" "chown www-data:www-data /var/www/rent-map/fmr.meta.json"
    echo "  shipped fmr.meta.json ($(python3 -c 'import json;m=json.load(open("data/fmr.meta.json"));print("FY%d effective %s" % (m["fiscal_year"], m["effective"]))' 2>/dev/null || echo 'unreadable'))"
  else
    echo "  ! no fmr.meta.json — build_fmr.py did not write one; the site cannot date these figures"
  fi
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] FMR refresh complete"
}

main "$@"
