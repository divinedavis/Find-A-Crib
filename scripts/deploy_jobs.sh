#!/usr/bin/env bash
# Ship the cron-job sandbox (deploy/cron-rentmap-*, fac-run, sudoers, logrotate)
# to the droplet and update the jobs' checkout. See deploy/install_jobs.sh.
#
#   ./scripts/deploy_jobs.sh
#
# The checkout /root/Find-A-Crib is pulled AS `scraper` (its owner since
# 2026-10-07). Root never runs git in it: it is writable by the job user.
set -euo pipefail
HOST="${FAC_HOST:-root@142.93.183.172}"
cd "$(dirname "$0")/.."
echo "==> unit tests"
"${PY:-$HOME/.venvs/dhcr-map/bin/python}" tests/run_unit.py 2>/dev/null
STAGE=/root/fac-jobs-stage
ssh "$HOST" "rm -rf $STAGE && install -d -m 0700 $STAGE"
scp -q deploy/install_jobs.sh deploy/fac-run deploy/sudoers-fac-jobs deploy/logrotate-rentmap \
       deploy/cron-rentmap-* scripts/refresh_geoip.sh "$HOST:$STAGE/"
ssh "$HOST" "set -e
  if [ \"\$(stat -c %U /root/Find-A-Crib)\" = scraper ]; then
    sudo -u scraper -H git -C /root/Find-A-Crib pull -q --rebase --autostash origin main
  else
    git -C /root/Find-A-Crib pull -q --rebase --autostash origin main   # first install only
  fi
  bash $STAGE/install_jobs.sh
  rm -rf $STAGE"
