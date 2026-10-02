#!/usr/bin/env bash
# Put the app shell back the way a deploy_app.sh snapshot found it.
#
#   scripts/rollback_app.sh              # list snapshots, newest last
#   scripts/rollback_app.sh 20261001T1830Z
#
# deploy_app.sh takes the snapshot right before every copy and calls this on
# its own when the live journeys fail twice. Only the files deploy_app.sh
# ships are in a snapshot; data JSON and SEO pages have their own paths.
set -euo pipefail
HOST=root@104.236.120.144
DOC=/var/www/rent-map
BACKUPS=/var/backups/findacrib-app
SNAP=${1:-}
if [ -z "$SNAP" ]; then
  ssh "$HOST" "ls -1 $BACKUPS"
  exit 0
fi
ssh "$HOST" "set -e; test -d $BACKUPS/$SNAP; cd $BACKUPS/$SNAP
  find . -type f | while read -r f; do install -D -m 644 -o root -g root \"\$f\" \"$DOC/\${f#./}\"; echo \"   restored \${f#./}\"; done"
for u in / /la/ /sf/ /dc/ /westchester/; do
  printf '%-15s %s\n' "$u" "$(curl -s -o /dev/null -w '%{http_code}' "https://findacrib.com$u")"
done
echo "rolled back to $SNAP"
