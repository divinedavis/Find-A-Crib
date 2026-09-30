#!/usr/bin/env bash
# Ship the Business & legal page's private catalog (company steps + app list)
# to the droplet. The source is on the owner's laptop, not in this public repo:
# it names the employer, clients, and which app holds patient data.
#
#   ./scripts/deploy_business_catalog.sh
#
set -euo pipefail
HOST="${FAC_HOST:-root@104.236.120.144}"
SRC="${BUSINESS_CATALOG:-$HOME/.config/business-dashboard/catalog.json}"
DIR=/var/lib/findacrib-api/business
python3 -c "import json,sys; c=json.load(open(sys.argv[1])); assert c['company'] and c['apps']" "$SRC"
ssh "$HOST" "install -d -m 700 -o findacrib -g findacrib $DIR"
scp -q "$SRC" "$HOST:$DIR/catalog.json.new"
ssh "$HOST" "chown findacrib:findacrib $DIR/catalog.json.new && chmod 600 $DIR/catalog.json.new && mv $DIR/catalog.json.new $DIR/catalog.json"
echo "catalog live ($(python3 -c "import json,sys; c=json.load(open(sys.argv[1])); print(len(c['apps']), 'apps,', len(c['company']), 'company rows')" "$SRC"))"
