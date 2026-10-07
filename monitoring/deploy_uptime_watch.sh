#!/usr/bin/env bash
# Install monitoring/uptime_watch.py on both droplets (each watches the
# other's sites) with a 5-minute cron. SMTP settings are copied once from
# the findacrib droplet's growth.env into /etc/uptime-watch.env (0600) on
# each box — box to box, never through a file on this Mac.
#   monitoring/deploy_uptime_watch.sh
set -euo pipefail
cd "$(dirname "$0")"
SRC=root@142.93.183.172   # Find A Crib droplet (holds growth.env) since 2026-10-06
for H in root@104.236.120.144 root@159.203.110.79; do
  echo "== $H"
  scp -q uptime_watch.py "$H:/usr/local/bin/uptime-watch"
  ssh "$H" "chmod 755 /usr/local/bin/uptime-watch && mkdir -p /var/lib/uptime-watch
    echo '*/5 * * * * root /usr/local/bin/uptime-watch >> /var/log/uptime-watch.log 2>&1' > /etc/cron.d/uptime-watch
    chmod 644 /etc/cron.d/uptime-watch"
  if ! ssh "$H" test -s /etc/uptime-watch.env; then
    { ssh "$SRC" "grep -E '^SMTP_(HOST|PORT|USER|PASSWORD)=' /root/Find-A-Crib/growth.env; grep -E '^ERROR_REPORT_EMAIL=' /root/Find-A-Crib/growth.env | sed 's/^ERROR_REPORT_EMAIL=/ALERT_TO=/'"; } \
      | ssh "$H" "umask 077; cat > /etc/uptime-watch.env"
    echo "   wrote /etc/uptime-watch.env"
  fi
  ssh "$H" "/usr/local/bin/uptime-watch && cat /var/lib/uptime-watch/state.json"
done
