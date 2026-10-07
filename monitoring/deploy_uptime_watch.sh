#!/usr/bin/env bash
# Install monitoring/uptime_watch.py on 104.236 and 167.71 (each skips the
# sites it hosts itself, so 167 watches 104.236 and 104.236 watches the rest)
# with a 5-minute cron. 159.203.110.79 was merged into 104.236 on 2026-10-07.
# SMTP settings are copied once from 104.236's /etc/uptime-watch.env (0600)
# to any box that lacks it -- box to box, never through a file on this Mac.
#   monitoring/deploy_uptime_watch.sh
set -euo pipefail
cd "$(dirname "$0")"
SRC=root@104.236.120.144   # holds /etc/uptime-watch.env (SMTP copied from FAC growth.env on 2026-10-01)
for H in root@104.236.120.144 root@167.71.170.219; do
  echo "== $H"
  scp -q uptime_watch.py "$H:/usr/local/bin/uptime-watch"
  ssh "$H" "chmod 755 /usr/local/bin/uptime-watch && mkdir -p /var/lib/uptime-watch
    echo '*/5 * * * * root /usr/local/bin/uptime-watch >> /var/log/uptime-watch.log 2>&1' > /etc/cron.d/uptime-watch
    chmod 644 /etc/cron.d/uptime-watch"
  if ! ssh "$H" test -s /etc/uptime-watch.env; then
    ssh "$SRC" "cat /etc/uptime-watch.env" | ssh "$H" "umask 077; cat > /etc/uptime-watch.env"
    echo "   wrote /etc/uptime-watch.env"
  fi
  ssh "$H" "/usr/local/bin/uptime-watch && cat /var/lib/uptime-watch/state.json"
done
