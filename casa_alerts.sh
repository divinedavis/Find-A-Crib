#!/bin/bash
# Your Casa alerts, every 30 minutes: new 311 calls on each Plus member's
# watched building, and crime kinds they picked when the NYPD's quarterly
# release lands. Installed by /etc/cron.d/rentmap-casa. See casa_alerts.py.
set -uo pipefail
cd /root/Find-A-Crib || exit 1
if [ -z "${FAC_ENV_LOADED:-}" ] && [ -f ./growth.env ]; then set -a; . ./growth.env; set +a; fi
/usr/bin/python3 casa_alerts.py "$@"
