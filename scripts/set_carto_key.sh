#!/usr/bin/env bash
# Install the CARTO Basemaps API key.
#
# CARTO stamps "API KEY REQUIRED" into unauthenticated raster tiles, so the map
# is watermarked for every visitor until a key is in place. Get one (free to 5M
# tiles/month, no account, no approval queue) at https://carto.com/basemaps/apikey
# then run:   scripts/set_carto_key.sh <key>
#
# config.js is gitignored and exists in two places that both matter: the local
# copy (so `python3 -m http.server` matches production) and the droplet's copy,
# which is the one findacrib.com actually serves — to all four cities, since
# /sf /la /dc load ../config.js. nginx sends no-cache on it, so there is no
# cache-buster to bump.
set -euo pipefail

KEY="${1:-}"
[ -n "$KEY" ] || { echo "usage: $0 <carto-api-key>"; exit 1; }
case "$KEY" in *[![:alnum:]_.-]*) echo "refusing: key has characters a URL query would mangle"; exit 1;; esac

HOST=root@104.236.120.144
REMOTE=/var/www/rent-map/config.js
LOCAL="$(cd "$(dirname "$0")/.." && pwd)/config.js"

set_key() {   # file
  local f="$1"
  [ -f "$f" ] || { echo "missing $f"; return 1; }
  if grep -q '^window.CARTO_KEY' "$f"; then
    # BSD and GNU sed disagree about -i; write a new file and move it instead.
    grep -v '^window.CARTO_KEY' "$f" > "$f.tmp"
  else
    cp "$f" "$f.tmp"
    printf '\n// CARTO Basemaps — https://carto.com/basemaps/apikey (free to 5M tiles/month)\n' >> "$f.tmp"
  fi
  printf "window.CARTO_KEY = '%s';\n" "$KEY" >> "$f.tmp"
  mv "$f.tmp" "$f"
}

echo "→ local  $LOCAL";  set_key "$LOCAL"
echo "→ remote $HOST:$REMOTE"
ssh "$HOST" "cp $REMOTE $REMOTE.bak"
scp -q "$LOCAL" "$HOST:$REMOTE"
ssh "$HOST" "chown www-data:www-data $REMOTE"

echo "→ verifying the key is served"
curl -fsS "https://findacrib.com/config.js" | grep -q "CARTO_KEY = '$KEY'" \
  && echo "  config.js OK" || { echo "  FAILED: key not in the served config.js"; exit 1; }

echo "→ verifying CARTO accepts it (a rejected key still returns a watermarked 200)"
TILE="https://a.basemaps.cartocdn.com/rastertiles/dark_all/13/2411/3079.png"
plain=$(curl -fsS "$TILE"            | shasum -a 256 | cut -d' ' -f1)
keyed=$(curl -fsS "$TILE?key=$KEY"   | shasum -a 256 | cut -d' ' -f1)
if [ "$plain" = "$keyed" ]; then
  echo "  WARNING: keyed tile is byte-identical to the unauthenticated one —"
  echo "  the key is not being honoured yet. Check it against CARTO's email."
  exit 1
fi
echo "  tiles differ — the key is live. Hard-reload findacrib.com to see it."
