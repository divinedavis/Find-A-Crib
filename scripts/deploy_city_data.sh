#!/usr/bin/env bash
# Ship a city's buildings files to the findacrib.com docroot.
#
#   scripts/deploy_city_data.sh              # every city
#   scripts/deploy_city_data.sh la dc        # just these
#
# NYC's own buildings files are NOT handled here: the droplet rebuilds those in
# place (refresh_hpd_counts.py weekly, then split_hpd.py from refresh_seo.sh
# nightly), and copying a laptop's copy over them would undo whichever ran last.
# The other cities have no cron at all yet — their builders run here and their
# output is carried over by hand, which is what this is.
#
# Order matters. buildings.slim.json is what the app boots from and
# buildings.hpd.json is fetched on the first building open, so the .gz beside
# each one is what nginx actually serves (gzip_static). A stale .gz next to a
# fresh .json is the one failure mode that looks like nothing happened, so each
# file is sent with its .gz or not at all.
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=root@104.236.120.144
DOC=/var/www/rent-map
CITIES=("$@")
if [ ${#CITIES[@]} -eq 0 ]; then CITIES=(la sf dc westchester); fi

for c in "${CITIES[@]}"; do
  [ -d "$c" ] || { echo "!! no $c/ directory"; exit 1; }
  echo "== $c"
  for f in buildings.min.json buildings.slim.json buildings.hpd.json; do
    [ -f "$c/$f" ] || continue
    if [ ! -f "$c/$f.gz" ] || [ "$c/$f" -nt "$c/$f.gz" ]; then
      echo "   recompressing $f.gz (it was older than the json)"
      gzip -9 -kf "$c/$f"
    fi
    printf '   %-22s %6.2f MB raw / %5.2f MB gz\n' "$f" \
      "$(echo "scale=2; $(wc -c <"$c/$f") / 1000000" | bc)" \
      "$(echo "scale=2; $(wc -c <"$c/$f.gz") / 1000000" | bc)"
    scp -q "$c/$f" "$c/$f.gz" "$HOST:$DOC/$c/"
  done
done

echo
echo "== what the site serves now"
for c in "${CITIES[@]}"; do
  for f in buildings.slim.json buildings.hpd.json; do
    [ -f "$c/$f" ] || continue
    printf '%-34s %s  %s bytes\n' "/$c/$f" \
      "$(curl -s -o /dev/null -w '%{http_code}' "https://findacrib.com/$c/$f")" \
      "$(curl -s -o /dev/null -w '%{size_download}' -H 'Accept-Encoding: gzip' "https://findacrib.com/$c/$f")"
  done
done
