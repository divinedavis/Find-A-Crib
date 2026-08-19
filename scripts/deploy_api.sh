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
#   ./scripts/deploy_api.sh                 # pull on the box, sync, restart
#
set -euo pipefail
HOST="${FAC_HOST:-root@104.236.120.144}"
REPO=/root/Find-A-Crib
LIVE=/root/findacrib-api
# Exactly the modules gunicorn imports. Listed rather than globbed: the repo is
# a website with a hundred scripts in its root, and the API directory should
# hold the six files it runs.
FILES=(api_server.py crease_metrics.py nemo_metrics.py build_log.py building_report.py issue_api_key.py)

ssh "$HOST" "set -e
  cd $REPO && git pull -q --ff-only
  for f in ${FILES[*]}; do
    cmp -s $REPO/\$f $LIVE/\$f || echo \"    updating \$f\"
    cp $REPO/\$f $LIVE/\$f
  done
  # Stale bytecode outlives a file copy when the mtime granularity is coarse.
  rm -rf $LIVE/__pycache__
  systemctl restart findacrib-api"

sleep 4
ssh "$HOST" "set -e
  systemctl is-active findacrib-api
  cd $LIVE && ./venv/bin/python -c \"
import crease_metrics, nemo_metrics
t = crease_metrics.traffic('all')
print('    crease traffic:', {k: t[k] for k in ('visitors', 'visits', 'visitors_today')})
\"
  # The gate is the point: a 401 here is the owner check working, and anything
  # else — a 500, a 502 — is a module that imported on the command line and
  # broke inside the worker.
  code=\$(curl -s -o /dev/null -w '%{http_code}' -m 10 https://findacrib.com/api/dashboard-crease)
  echo \"    /api/dashboard-crease -> \$code (expect 401 unauthenticated)\"
  test \"\$code\" = 401"
echo "==> done"
