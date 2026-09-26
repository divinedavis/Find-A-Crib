#!/bin/bash
# Saved-building alerts, every morning: diff every building anyone has saved
# against yesterday's snapshot and mail the people watching it. Tuesdays the
# same run sends the weekly round-up instead (saved_alerts.py decides by the
# New York weekday). Installed by /etc/cron.d/rentmap-saved.
#
# Reads the feeds the site already serves from the docroot (buildings.min.json,
# listings.json, s8.json, housing_connect.json, hcr.json) and rerental_new.json
# from the checkout. No git pull here — the 05:00 growth run pulls daily.
set -uo pipefail
cd /root/Find-A-Crib || exit 1
export GROWTH_DOCROOT=${GROWTH_DOCROOT:-/var/www/rent-map}
if [ -f ./growth.env ]; then set -a; . ./growth.env; set +a; fi
/usr/bin/python3 saved_alerts.py "$@"
