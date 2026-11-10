#!/usr/bin/env bash
# Diff the live nginx config on the droplet against deploy/nginx/.
#
#   scripts/check_nginx_drift.sh          # exit 1 if anything differs
#   FAC_HOST=root@host scripts/check_nginx_drift.sh
#
# Read-only: it cats four files over SSH and runs diff locally. The snapshot is
# documented in deploy/nginx/README.md.
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=${FAC_HOST:-root@142.93.183.172}
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10)
# The owner's ~/.ssh/config multiplexes every connection (fail2ban on the old
# box). In a sandbox where ~/.ssh/cm is not writable, set FAC_SSH_NO_MUX=1.
if [ "${FAC_SSH_NO_MUX:-0}" = 1 ]; then
  SSH_OPTS+=(-o ControlMaster=no -o ControlPath=none -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
fi
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fail=0
check() {
  local live=$1 snapshot=$2 name
  name=$(basename "$live")
  # shellcheck disable=SC2029  # $live is a fixed path, intentionally client-side
  if ! ssh "${SSH_OPTS[@]}" "$HOST" "cat '$live'" >"$TMP/$name" 2>"$TMP/$name.err"; then
    echo "!! cannot read $live on $HOST"
    sed -n 1,3p "$TMP/$name.err" >&2 || true
    fail=1
    return
  fi
  if diff -u "$snapshot" "$TMP/$name" >"$TMP/$name.diff"; then
    echo "ok    $live"
  else
    echo "DRIFT $live"
    sed -n 1,60p "$TMP/$name.diff"
    fail=1
  fi
}
check /etc/nginx/sites-available/findacrib        deploy/nginx/sites-available/findacrib.conf
check /etc/nginx/sites-available/default-drop     deploy/nginx/sites-available/default-drop.conf
check /etc/nginx/conf.d/ratelimit.conf            deploy/nginx/conf.d/ratelimit.conf
check /etc/nginx/conf.d/log_format_site.conf      deploy/nginx/conf.d/log_format_site.conf
if [ "$fail" -ne 0 ]; then
  echo
  echo "Live nginx differs from deploy/nginx/. If the change is intentional,"
  echo "update the snapshot in the same commit that changed the vhost."
fi
exit "$fail"
