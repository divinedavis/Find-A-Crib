#!/usr/bin/env bash
# Ship the owner dashboard to divinedavis.com/dashboard/.
#
# The page lives in this repo because it is coupled to api_server.py's
# /dashboard-* routes, but it is served by the divinedavis.com droplet. Its
# nginx proxies /api/dashboard-* to findacrib.com, so the page's fetches stay
# same-origin and need no CORS. findacrib.com/dashboard/ 301s here.
#
# The divinedavis docroot is a plain directory (no checkout, generated files
# beside the site), so this copies exactly the dashboard files and nothing else.
#
#   ./scripts/deploy_dashboard.sh
#
set -euo pipefail
cd "$(dirname "$0")/.."
HOST="${DD_HOST:-root@159.203.110.79}"
DEST=/var/www/divinedavis/dashboard

ssh "$HOST" "mkdir -p $DEST/users"
scp -q dashboard/index.html dashboard/og-dashboard.png dashboard/supabase-config.js "$HOST:$DEST/"
scp -q static/supabase/supabase.js "$HOST:$DEST/supabase.js"
scp -q dashboard/users/index.html "$HOST:$DEST/users/index.html"
ssh "$HOST" "chown -R www-data:www-data $DEST"

# md5, not a 200: a stale copy answers 200 too.
for pair in index.html:dashboard/index.html users/index.html:dashboard/users/index.html \
            supabase-config.js:dashboard/supabase-config.js supabase.js:static/supabase/supabase.js; do
  remote=${pair%%:*}; local=${pair#*:}
  live=$(curl -fsS "https://divinedavis.com/dashboard/$remote" | md5)
  [ "$live" = "$(md5 -q "$local")" ] || { echo "MISMATCH: /dashboard/$remote"; exit 1; }
done
echo "dashboard live at https://divinedavis.com/dashboard/"
