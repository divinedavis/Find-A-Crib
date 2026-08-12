#!/bin/bash
# Nightly SEO refresh: rebuild static pages from the latest data, deploy only
# changed/new files, and ping IndexNow with the URLs that actually changed.
# Runs after the Zumper scrape (which refreshes listings.json). Honest lastmod:
# build_seo.py only bumps a page's <lastmod> when its HTML really changed.
set -euo pipefail
BUILD=/root/dhcr-build
DOC=/var/www/rent-map
cd "$BUILD"

# ------------------------------------------------------------------ heartbeat
# This pipeline publishes 47,599 of the site's ~47,600 pages and, until
# 2026-08-12, was the only one on the droplet that reported nothing at all about
# itself. growth_run.sh got a heartbeat on 2026-08-10; this one had none, and it
# is the pipeline that matters most.
#
# What that cost: the daily review agent runs in Anthropic's cloud with no
# droplet access, so the only evidence it had was the mtime of the corpus in the
# docroot — "the SEO corpus was last written 2026-08-08 (4d ago)". That single
# fact is consistent with three completely different failures needing three
# different fixes: the cron never fired, build_seo.py crashed, or the rsync into
# the docroot failed. Four mornings running, nobody could tell which.
#
# So: write a small status record into the docroot at start, and again on exit
# whatever the exit code, naming the step that was in flight. The 05:40 growth
# build runs after this one, reads the file (techniques._seo_pipeline_status)
# and folds it into growth/last_run.json, which it commits and pushes. The
# docroot is the only place both pipelines can see and that push is the only
# channel that reaches the cloud, so this is the whole route.
#
# STRUCTURED FIELDS ONLY — never captured command output, never file contents.
# growth_run.sh's heartbeat may carry two lines of a traceback because it writes
# into a git repo it controls; this one writes into $DOC, which is web-served,
# from $BUILD, which holds indexnow.key. A step name plus an exit code is the
# entire diagnosis anyone needed, and it cannot leak anything.
#
# Every write is best-effort (|| true): a heartbeat must never be the reason the
# night's rebuild does not happen.
STATUS="$DOC/.seo-build-status.json"
STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
STEP=startup          # the step currently in flight; the trap reports it
CHANGED_N=0           # URLs build_seo.py says really changed
CORPUS_N=0            # pages in the built corpus — a truncated build looks
                      # identical to a good one from the docroot's mtime alone

status() {
  {
    printf '{"started":"%s","at":"%s","phase":"%s","step":"%s","rc":%s,"head":"%s","changed_urls":%s,"corpus_pages":%s}\n' \
      "$STARTED" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$STEP" "${2:-null}" \
      "$(git -C "$BUILD" rev-parse --short HEAD 2>/dev/null || echo unknown)" \
      "$CHANGED_N" "$CORPUS_N" > "$STATUS.tmp" && mv -f "$STATUS.tmp" "$STATUS"
  } 2>/dev/null || true
}

# set -e means almost every failure leaves through EXIT, so the trap is what
# turns "the script stopped" into "the script stopped in step <x> with rc <n>".
# The trap does not call exit, so bash keeps the real exit status.
trap 'status finish $?' EXIT
status start

# Take whatever the daily review agent pushed. It runs in Anthropic's cloud with
# only a git checkout, so git is the only way its content changes (seo_guides.py,
# build_seo.py) reach this build. Guarded and non-fatal: if $BUILD is not a git
# worktree, or the pull fails, build from whatever is on disk rather than
# skipping the night's rebuild entirely.
STEP=pull
if git -C "$BUILD" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$BUILD" pull --rebase --autostash -q origin main \
    || echo "refresh_seo: git pull failed, building from the local copy"
else
  echo "refresh_seo: $BUILD is not a git worktree, building from the local copy"
fi

STEP=build
python3 build_seo.py

# Count what the build actually produced, before anything is deployed. Every
# page build_seo.py writes is a <path>/index.html under $BUILD/seo, so this is
# the corpus size. `find || true` inside the braces because pipefail would
# otherwise let a find error and the `|| echo 0` fallback both reach wc.
STEP=count
CORPUS_N=$( { find "$BUILD/seo" -name index.html 2>/dev/null || true; } | wc -l )
CORPUS_N=$((CORPUS_N + 0))
CHANGED="$BUILD/seo/changed_urls.txt"
# Braces so 2>/dev/null also swallows bash's own "No such file" for the input
# redirection, which is reported before wc ever runs.
CHANGED_N=$( { wc -l < "$CHANGED"; } 2>/dev/null || echo 0)
CHANGED_N=$((CHANGED_N + 0))
status built

# deploy: copy changed/new pages into the docroot. NO --delete — the docroot
# also holds the app (index.html, config.js, buildings.min.json, scraper, venv).
STEP=deploy
rsync -a --exclude changed_urls.txt "$BUILD/seo/" "$DOC/"
status deployed

# tell IndexNow (Bing, Yandex, Seznam…) about changed URLs. Google ignores
# IndexNow and instead re-crawls from the sitemap <lastmod> we just updated.
STEP=indexnow
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
STEP=done
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] refresh complete: $CORPUS_N pages built, $CHANGED_N changed"
