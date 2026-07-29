#!/bin/bash
# Nightly SEO refresh: rebuild static pages from the latest data, deploy only
# changed/new files, and ping IndexNow with the URLs that actually changed.
# Runs after the Zumper scrape (which refreshes listings.json). Honest lastmod:
# build_seo.py only bumps a page's <lastmod> when its HTML really changed.
set -euo pipefail
BUILD=/root/dhcr-build
DOC=/var/www/rent-map
cd "$BUILD"

# Take whatever the daily review agent pushed. It runs in Anthropic's cloud with
# only a git checkout, so git is the only way its content changes (seo_guides.py,
# build_seo.py) reach this build. Guarded and non-fatal: if $BUILD is not a git
# worktree, or the pull fails, build from whatever is on disk rather than
# skipping the night's rebuild entirely.
if git -C "$BUILD" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$BUILD" pull --rebase --autostash -q origin main \
    || echo "refresh_seo: git pull failed, building from the local copy"
else
  echo "refresh_seo: $BUILD is not a git worktree, building from the local copy"
fi

python3 build_seo.py

# deploy: copy changed/new pages into the docroot. NO --delete — the docroot
# also holds the app (index.html, config.js, buildings.min.json, scraper, venv).
rsync -a --exclude changed_urls.txt "$BUILD/seo/" "$DOC/"

# tell IndexNow (Bing, Yandex, Seznam…) about changed URLs. Google ignores
# IndexNow and instead re-crawls from the sitemap <lastmod> we just updated.
CHANGED="$BUILD/seo/changed_urls.txt"
KEY="$(cat "$BUILD/indexnow.key")"
if [ -s "$CHANGED" ]; then
  python3 - "$CHANGED" "$KEY" <<'PY'
import sys, json, urllib.request
urls = [l.strip() for l in open(sys.argv[1]) if l.strip()]
key = sys.argv[2]
if not urls:
    print("IndexNow: nothing changed"); raise SystemExit
payload = {"host": "findacrib.com", "key": key,
           "keyLocation": f"https://findacrib.com/{key}.txt",
           "urlList": urls[:10000]}
req = urllib.request.Request("https://api.indexnow.org/indexnow",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json; charset=utf-8"})
try:
    r = urllib.request.urlopen(req, timeout=30)
    print(f"IndexNow: submitted {len(urls)} urls -> HTTP {r.status}")
except Exception as e:
    print("IndexNow submit failed:", e)
PY
else
  echo "IndexNow: no changed pages this run"
fi
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] refresh complete"
