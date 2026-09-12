#!/usr/bin/env bash
# Rebuild a city's buildings files from source and ship them.
#
#   scripts/refresh_cities.sh              # all three
#   scripts/refresh_cities.sh la           # just LA
#   NO_DEPLOY=1 scripts/refresh_cities.sh  # build only, don't touch the droplet
#
# Each city is two steps and then the split, in that order, because each step
# writes the file the next one reads:
#
#   build_<city>.py          the register itself      -> <city>/buildings.min.json
#   build_<city>_records.py  the per-property record   -> adds `h` in place
#   split_hpd.py             boot payload / lazy blob  -> .slim.json + .hpd.json
#
# Running the records builder without re-running its register builder first is
# fine and much faster (the Socrata and DCGIS pulls cache under <city>_raw/ and
# dc_raw/); running the register builder WITHOUT the records builder after it
# silently drops every `h` on the floor, because build_<city>.py rewrites the
# file from scratch. So they are chained here and not meant to be run apart.
#
# Refresh cadence of the sources, measured 2026-09-12:
#   LA   LAHD property look-ups update daily-ish; the assessor layer monthly
#   SF   DataSF refreshes the inventory and the case files every 24h
#   DC   RentRegistry exports nightly; DCGIS/CAMA a few times a year
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-$HOME/.venvs/dhcr-map/bin/python}
CITIES=("$@")
if [ ${#CITIES[@]} -eq 0 ]; then CITIES=(la sf dc); fi

for c in "${CITIES[@]}"; do
  echo
  echo "################ $c"
  case "$c" in
    la) "$PY" build_la.py && "$PY" build_la_records.py ;;
    sf) "$PY" build_sf.py && "$PY" build_sf_records.py ;;
    dc) "$PY" build_dc.py && "$PY" build_dc_records.py ;;
    *)  echo "!! no builder for $c" >&2; exit 1 ;;
  esac
  "$PY" split_hpd.py --docroot "$c"
  gzip -9 -kf "$c/buildings.min.json"
done

if [ "${NO_DEPLOY:-}" = "1" ]; then
  echo; echo "NO_DEPLOY=1 — built but not shipped. scripts/deploy_city_data.sh ${CITIES[*]} when ready."
  exit 0
fi
echo
exec scripts/deploy_city_data.sh "${CITIES[@]}"
