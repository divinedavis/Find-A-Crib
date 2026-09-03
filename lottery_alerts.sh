#!/bin/bash
# Borough alerts, every 10 minutes: refresh the Housing Connect feed (one POST
# to HPD's public API), welcome anyone who signed up since the last run, then
# mail whatever is new in housing_connect.json / hcr.json / rerental_new.json
# to the subscribers watching that borough.
#
# hcr.json is refreshed hourly by /etc/cron.d/rentmap-hcr (--incremental) and
# rerental_new.json by the re-rental sweeps in /etc/cron.d/rentmap-rerentals;
# this job only reads those two.
#
# Not set -e: a failed Housing Connect refresh keeps the previous file and the
# dispatcher still runs on the other feeds. No git pull here either — the
# 05:00 growth run and the 06:45 sweep pull the checkout daily, and pulling
# 144 times a day would only add churn.
set -uo pipefail
cd /root/Find-A-Crib || exit 1
export GROWTH_DOCROOT=${GROWTH_DOCROOT:-/var/www/rent-map}
if [ -f ./growth.env ]; then set -a; . ./growth.env; set +a; fi

out=$(/usr/bin/python3 housing_connect.py --apply --out "$GROWTH_DOCROOT" 2>&1) \
  || echo "alerts: housing_connect refresh failed: $(printf '%s' "$out" | tail -1)"

/usr/bin/python3 lottery_alerts.py --welcome
/usr/bin/python3 lottery_alerts.py "$@"
