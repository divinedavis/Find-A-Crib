#!/usr/bin/env bash
# Refresh the IP-to-city database the /api/geo endpoint reads.
#
# DB-IP's "IP to City Lite" (CC BY 4.0 — credited on /privacy.html) is a free
# monthly MMDB with no account or license key, unlike MaxMind's GeoLite2.
# The file is named by year-month; it is published on the 1st. Installed as
# /etc/cron.d/rentmap-geoip (deploy/cron-rentmap-geoip), and run once by hand
# on install.
#
#   ./scripts/refresh_geoip.sh            # fetch this month's file if missing
#
# The API opens the database lazily on each request through a small cache, so
# a swapped file is picked up without a restart.
set -euo pipefail
LIVE=/root/findacrib-api
OUT="$LIVE/dbip-city-lite.mmdb"
ym=$(date -u +%Y-%m)
url="https://download.db-ip.com/free/dbip-city-lite-${ym}.mmdb.gz"
tmp=$(mktemp)
trap 'rm -f "$tmp" "$tmp.gz"' EXIT
if ! curl -fsSL -m 300 -o "$tmp.gz" "$url"; then
  # Early in the month the new file may not exist yet: keep last month's.
  echo "geoip: $url not available; keeping $(stat -c %y "$OUT" 2>/dev/null || echo 'nothing')"
  exit 0
fi
gunzip -c "$tmp.gz" > "$tmp"
# Sanity: a real MMDB ends with the metadata marker.
if ! tail -c 200000 "$tmp" | grep -q "MaxMind.com"; then
  echo "geoip: downloaded file is not an MMDB; keeping the old one" >&2
  exit 1
fi
install -m 0644 "$tmp" "$OUT"
echo "geoip: installed $(basename "$url") ($(du -h "$OUT" | cut -f1))"
