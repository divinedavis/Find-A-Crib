#!/usr/bin/env bash
# Fail if findacrib.com serves any file that must never be public.
#
# On 2026-07-15 a one-off copy from the laptop dropped agent_phones.json and
# the pipeline intermediates (buildings_hpd.json carries manager.phone) into
# /var/www/rent-map, where nginx served them for ten weeks — 11.5k Plus-only
# phone numbers, free (security audit 2026-09-25). No deploy script copies
# them today; the nginx deny rule in sites-enabled/findacrib blocks them
# anyway. This probe proves both still hold, and deploy_app.sh runs it.
#
#   scripts/check_docroot_leaks.sh
set -uo pipefail
BASE=${BASE:-https://findacrib.com}
PATHS=(
  agent_phones.json buildings_hpd.json buildings.json buildings_geo.json
  buildings_geo_nta.json config.js.bak index.html.bak README.md
  changed_urls.txt scripts/refresh_listings.sh venv/pyvenv.cfg hcr_chain.pem
  api_server.py scrape.log alert_snapshot.json buildings_cache.json .env
)
bad=0
for p in "${PATHS[@]}"; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$BASE/$p")
  if [ "$code" = 200 ]; then echo "LEAK  /$p -> 200"; bad=1; fi
done
[ $bad = 0 ] && echo "docroot leak probe: ${#PATHS[@]} private paths, none served"
exit $bad
