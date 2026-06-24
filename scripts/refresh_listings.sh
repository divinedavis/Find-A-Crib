#!/bin/bash
# Nightly rent refresh: pull the Apify StreetEasy dataset, match listings to
# DHCR buildings, and rewrite listings.json in place. Replaces the old Zumper
# Playwright scrape (scrape_listings.py) — stdlib only, no venv needed.
#
# Secrets come from /etc/rentmap-apify.env (chmod 600), e.g.:
#   APIFY_TOKEN=apify_api_xxx
#   APIFY_TASK=<your-streeteasy-task-id>
# The SEO cron (refresh_seo.sh, 04:10 UTC) runs after this and picks up the
# refreshed listings.json.
set -euo pipefail
DOC=/var/www/rent-map
cd "$DOC"

# load Apify creds
set -a; . /etc/rentmap-apify.env; set +a

# Monthly per-borough Apify run. Pass the borough as $1 (BK|MN|BX|QN|SI) so the
# parse pins to it (stray cross-borough matches dropped) and --merge accumulates
# it into listings_apify.json alongside prior months' boroughs. combine then
# overlays Apify onto the Zumper baseline to rebuild listings.json.
BOROUGH="${1:?usage: refresh_listings.sh <BK|MN|BX|QN|SI>}"
python3 fetch_apify.py apify_export.json
python3 parse_apify.py apify_export.json --merge --borough "$BOROUGH"
python3 combine_listings.py

echo "listings refreshed ($BOROUGH): $(date -u)"
