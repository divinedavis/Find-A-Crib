#!/usr/bin/env bash
# Pull the current public data files from findacrib.com into the app bundle's
# seed copy. The app refreshes these itself at runtime (ETag-conditional), so
# this only needs running before a ship so first launch isn't stale.
set -euo pipefail
cd "$(dirname "$0")/.."
D=FindACrib/Resources/Data
for f in listings.json s8.json fmr.json; do
  curl -fsS "https://findacrib.com/$f" -o "$D/$f"
done
curl -fsS -H "Accept-Encoding: gzip" "https://findacrib.com/buildings.slim.json.gz" -o "$D/buildings.slim.json.gz"
ls -la "$D"
