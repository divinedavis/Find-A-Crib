#!/usr/bin/env bash
# Ship the dashboard API to the droplet — and to the directory it actually
# runs from.
#
# findacrib-api is a gunicorn app whose WorkingDirectory is /root/findacrib-api,
# which is NOT a git checkout: it is a hand-copied set of modules living beside
# the repo at /root/Find-A-Crib. Pulling the repo and restarting the service
# therefore does nothing at all, silently — on 2026-08-19 a rewritten visitor
# filter was pulled, the service was restarted, the module was verified by hand
# in the checkout, and the dashboard went on serving the old numbers from the
# other copy for an hour.
#
# It runs as the nologin user `findacrib`, not root (2026-09-26): the drop-in
# in deploy/ sets User=, the state dir and the cache paths, and this script
# re-applies the code dir's ownership after every copy.
#
#   ./scripts/deploy_api.sh                 # pull on the box, sync, restart
#
# Gates (2026-10-01): tests/run_unit.py runs locally first; the live modules
# are snapshotted to $BACKUPS before the copy; and if the post-restart checks
# fail, the snapshot goes back in, the service restarts on it, and this exits 1.
#
set -euo pipefail
HOST="${FAC_HOST:-root@104.236.120.144}"
REPO=/root/Find-A-Crib
LIVE=/root/findacrib-api
# Exactly the modules gunicorn imports. Listed rather than globbed: the repo is
# a website with a hundred scripts in its root, and the API directory should
# hold the six files it runs.
BACKUPS=/var/backups/findacrib-api
FILES=(api_server.py ai_gateway.py nl_search.py rent_check.py building_records.py claude_features.py listing_page.py flyer_reader.py creator_outreach.py business_checklist.py creator_mail_reader.py crease_metrics.py nemo_metrics.py trent_metrics.py marracat_metrics.py build_log.py building_report.py issue_api_key.py)

echo "==> unit tests"
cd "$(dirname "$0")/.."
"${PY:-$HOME/.venvs/dhcr-map/bin/python}" tests/run_unit.py 2>/dev/null

SNAP=$(date -u +%Y%m%dT%H%M%SZ)
echo "==> snapshotting live modules to $BACKUPS/$SNAP"
ssh "$HOST" "set -e; mkdir -p $BACKUPS/$SNAP
  for f in ${FILES[*]}; do [ -f $LIVE/\$f ] && cp -p $LIVE/\$f $BACKUPS/$SNAP/; done
  ls -1d $BACKUPS/*/ | head -n -15 | xargs -r rm -rf"

ssh "$HOST" "set -e
  cd $REPO && git pull -q --ff-only
  for f in ${FILES[*]}; do
    cmp -s $REPO/\$f $LIVE/\$f || echo \"    updating \$f\"
    cp $REPO/\$f $LIVE/\$f
  done
  # The unit's drop-in lives in the repo (deploy/), so a worker-count change
  # ships like any other and the box has nothing hand-edited to drift.
  mkdir -p /etc/systemd/system/findacrib-api.service.d
  cmp -s $REPO/deploy/findacrib-api.override.conf /etc/systemd/system/findacrib-api.service.d/override.conf || echo '    updating systemd override'
  cp $REPO/deploy/findacrib-api.override.conf /etc/systemd/system/findacrib-api.service.d/override.conf
  systemctl daemon-reload
  # Creator reply reader (hello@marracat.com rates -> the dashboard); cron.d
  # files must be root-owned 644 or cron ignores them. The Gmail forwarder it
  # replaced (2026-09-30) is removed so it can't keep running.
  install -m 644 -o root -g root $REPO/deploy/cron-creator-mail-reader /etc/cron.d/creator-mail-reader
  rm -f /etc/cron.d/creator-mail-forward $LIVE/creator_mail_forward.py
  # Stale bytecode outlives a file copy when the mtime granularity is coarse.
  rm -rf $LIVE/__pycache__
  # Since 2026-09-26 the API runs as the unprivileged user findacrib (see
  # deploy/findacrib-api.override.conf). Keep the code root-owned and
  # read-only to it; only the group may enter the dir or read .env. It writes
  # nothing here — its caches live in /var/lib/findacrib-api.
  chown -R root:root $LIVE && chmod -R go-w $LIVE
  chown root:findacrib $LIVE $LIVE/.env && chmod 0750 $LIVE && chmod 0640 $LIVE/.env
  systemctl restart findacrib-api"

sleep 4
if ! ssh "$HOST" "set -e
  systemctl is-active findacrib-api
  cd $LIVE && set -a && . ./.env && set +a && ./venv/bin/python -c \"
import crease_metrics, nemo_metrics, trent_metrics, marracat_metrics
t = crease_metrics.traffic('all')
print('    crease traffic:', {k: t[k] for k in ('visitors', 'visits', 'visitors_today')})
tt = trent_metrics.traffic('all')
print('    trent traffic:', {k: tt[k] for k in ('visitors', 'visits', 'visitors_today')})
m = marracat_metrics.build('all')
print('    marracat:', 'ok' if m.get('ok') else m.get('warnings'))
\"
  # The gate is the point: a 401 here is the owner check working, and anything
  # else — a 500, a 502 — is a module that imported on the command line and
  # broke inside the worker.
  for feed in dashboard-crease dashboard-trent dashboard-marracat; do
    code=\$(curl -s -o /dev/null -w '%{http_code}' -m 10 https://findacrib.com/api/\$feed)
    echo \"    /api/\$feed -> \$code (expect 401 unauthenticated)\"
    test \"\$code\" = 401
  done
  # ok:false is right from here — the droplet geolocates outside NYC. A
  # lookup that returns coordinates at all means the GeoIP DB loaded.
  code=\$(curl -s -o /tmp/geo.json -w '%{http_code}' -m 10 https://findacrib.com/api/geo)
  echo \"    /api/geo -> \$code \$(cat /tmp/geo.json)\"
  test \"\$code\" = 200 && grep -q '\"lat\":' /tmp/geo.json"; then
  echo "!! post-deploy checks failed — restoring $SNAP and restarting"
  ssh "$HOST" "set -e; cp -p $BACKUPS/$SNAP/* $LIVE/; rm -rf $LIVE/__pycache__
    chown -R root:root $LIVE && chmod -R go-w $LIVE
    chown root:findacrib $LIVE $LIVE/.env && chmod 0750 $LIVE && chmod 0640 $LIVE/.env
    systemctl restart findacrib-api; sleep 4; systemctl is-active findacrib-api"
  exit 1
fi
echo "==> done"
