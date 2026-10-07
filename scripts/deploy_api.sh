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
#   ./scripts/deploy_api.sh                 # copy this tree's modules, restart
#
# Gates (2026-10-01): tests/run_unit.py runs locally first; the live modules
# are snapshotted to $BACKUPS before the copy; and if the post-restart checks
# fail, the snapshot goes back in, the service restarts on it, and this exits 1.
#
set -euo pipefail
HOST="${FAC_HOST:-root@142.93.183.172}"
REPO=/root/Find-A-Crib   # the cron checkout; never read from here as root
LIVE=/root/findacrib-api
# Exactly the modules gunicorn imports. Listed rather than globbed: the repo is
# a website with a hundred scripts in its root, and the API directory should
# hold the six files it runs.
BACKUPS=/var/backups/findacrib-api
FILES=(api_server.py ai_gateway.py nl_search.py building_records.py claude_features.py listing_page.py flyer_reader.py build_log.py building_report.py issue_api_key.py)
# Modules that moved to the owner dashboard (repo divinedavis/owner-dashboard)
# on 2026-10-06; removed from the live dir so a stale copy can't be imported.
RETIRED=(creator_outreach.py business_checklist.py creator_mail_reader.py crease_metrics.py nemo_metrics.py trent_metrics.py marracat_metrics.py claude_usage.py nemo_payload_cache.json nemo_payload_cache.3m.json nemo_payload_cache.month.json nemo_payload_cache.today.json)

echo "==> unit tests"
cd "$(dirname "$0")/.."
"${PY:-$HOME/.venvs/dhcr-map/bin/python}" tests/run_unit.py 2>/dev/null

SNAP=$(date -u +%Y%m%dT%H%M%SZ)
echo "==> snapshotting live modules to $BACKUPS/$SNAP"
ssh "$HOST" "set -e; mkdir -p $BACKUPS/$SNAP
  for f in ${FILES[*]} ${RETIRED[*]}; do [ -f $LIVE/\$f ] && cp -p $LIVE/\$f $BACKUPS/$SNAP/; done
  ls -1d $BACKUPS/*/ | head -n -15 | xargs -r rm -rf"

# Ship THIS tree's files (the ones the unit tests just ran on), not a pull on
# the box. Since 2026-10-07 the droplet checkout $REPO belongs to the cron
# user `scraper`; copying API code or the systemd drop-in out of it as root
# would let anything that compromises a scraper job rewrite the API — or the
# unit's User= line — on the next deploy.
STAGE=/root/findacrib-api-stage
ssh "$HOST" "rm -rf $STAGE && install -d -m 0700 $STAGE"
scp -q "${FILES[@]}" deploy/findacrib-api.override.conf "$HOST:$STAGE/"
ssh "$HOST" "set -e
  for f in ${FILES[*]}; do
    cmp -s $STAGE/\$f $LIVE/\$f || echo \"    updating \$f\"
    cp $STAGE/\$f $LIVE/\$f
  done
  # The unit's drop-in lives in the repo (deploy/), so a worker-count change
  # ships like any other and the box has nothing hand-edited to drift.
  mkdir -p /etc/systemd/system/findacrib-api.service.d
  cmp -s $STAGE/findacrib-api.override.conf /etc/systemd/system/findacrib-api.service.d/override.conf || echo '    updating systemd override'
  cp $STAGE/findacrib-api.override.conf /etc/systemd/system/findacrib-api.service.d/override.conf
  rm -rf $STAGE
  systemctl daemon-reload
  for f in ${RETIRED[*]}; do rm -f $LIVE/\$f; done
  rm -f /etc/cron.d/creator-mail-reader /etc/cron.d/creator-mail-forward $LIVE/creator_mail_forward.py
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
  # The owner-dashboard read routes answer 401 without the key and 403 with a
  # wrong one; anything else (500, 502) is a module that broke in the worker.
  for feed in dashboard-metrics dashboard-users; do
    code=\$(curl -s -o /dev/null -w '%{http_code}' -m 10 https://findacrib.com/api/\$feed)
    echo \"    /api/\$feed -> \$code (expect 401 without the key)\"
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
