#!/bin/bash
# Nightly SEO refresh: rebuild static pages from the latest data, deploy only
# changed/new files, and ping IndexNow with the URLs that actually changed.
# Runs after the Zumper scrape (which refreshes listings.json). Honest lastmod:
# build_seo.py only bumps a page's <lastmod> when its HTML really changed.
set -euo pipefail
# Same variable growth_run.sh's watchdog reads, and the same default, so the two
# cannot disagree about which directory is the build. Overridable only so this
# script can be exercised against a scratch pair of directories — nothing on the
# droplet sets either.
BUILD=${SEO_BUILD_DIR:-/root/dhcr-build}
DOC=${SEO_DOCROOT:-/var/www/rent-map}

# Where THIS script lives, which is not where it builds — and it has to be
# resolved BEFORE the cd, while ${BASH_SOURCE[0]}'s relative path still means
# what it says. growth_run.sh invokes the copy in the checkout it has just
# pulled (see its seo_watchdog comment), so $SRC is current source while $BUILD
# is a separate directory holding the night's scraped data. When the old 04:10
# cron invokes $BUILD's own copy instead, $SRC resolves to $BUILD and every use
# of it below is a no-op.
SRC="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)" || SRC="$BUILD"

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
PULL_STATE=pending    # did $BUILD take the night's commits? see STEP=pull
CODE_STATE=pending    # …and if it did not, did we hand them over anyway?

status() {
  {
    printf '{"started":"%s","at":"%s","phase":"%s","step":"%s","rc":%s,"head":"%s","changed_urls":%s,"corpus_pages":%s,"pull":"%s","code":"%s"}\n' \
      "$STARTED" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$STEP" "${2:-null}" \
      "$(git -C "$BUILD" rev-parse --short HEAD 2>/dev/null || echo unknown)" \
      "$CHANGED_N" "$CORPUS_N" "$PULL_STATE" "$CODE_STATE" \
      > "$STATUS.tmp" && mv -f "$STATUS.tmp" "$STATUS"
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
  if git -C "$BUILD" pull --rebase --autostash -q origin main; then
    PULL_STATE=ok
  else
    PULL_STATE=failed
    echo "refresh_seo: git pull failed, building from the local copy"
  fi
else
  PULL_STATE=no-worktree
  echo "refresh_seo: $BUILD is not a git worktree, building from the local copy"
fi

# ------------------------------------------------------------- hand the code over
# The pull above has never once succeeded. Every .seo-build-status.json record in
# git — 2026-08-15 through 2026-08-22 — carries "head":"unknown", which is what
# `git -C $BUILD rev-parse HEAD` returns when $BUILD is not a git worktree at all,
# and that is the same condition the `if` above tests. So the else branch has been
# taken every night, its one line of explanation went to a stdout that
# growth_run.sh discards on purpose, and $BUILD/build_seo.py has been frozen since
# 2026-07-29. The 08-02 review called this "two doors, and only one opens"; the
# door has stayed shut for the 20 days since, because the only remedy anyone wrote
# down was an owner typing `git -C /root/dhcr-build pull` by hand.
#
# What proved it rather than merely suggesting it: on 2026-08-21 a review shipped
# a computed comparison paragraph to 46,853 of the 47,165 building pages. write()
# hashes everything but the <style> block, so a rebuild on that code cannot report
# fewer than ~46,853 changed URLs. The rebuild at 05:41 on 08-22 ran to completion,
# built 47,640 pages, and reported 0 changed. The generator that ran was not the
# generator in git.
#
# So stop waiting for the door. $SRC is a checkout that IS current; $BUILD holds
# the data. Copy the two source files the corpus is generated from across before
# building. Deliberately narrow:
#   * only when the pull did not already do it — a $BUILD that pulls is never touched;
#   * only these two files, named explicitly. Not data (buildings.min.json and
#     listings.json are scraped nightly INTO $BUILD and the checkout's copies are
#     stale), not seo_lastmod.json (per-corpus state; replacing it would bump every
#     lastmod on the site), not scripts/ (already run from $SRC);
#   * only if they differ, so a healthy build is byte-for-byte untouched;
#   * only if they compile, because replacing working code with code that does not
#     parse would publish nothing at all — the one outcome worse than stale pages;
#   * never a delete, never a move. Both files are in git and recoverable.
# Every step is non-fatal for the same reason the heartbeat is: this must not
# become the new reason the night's rebuild does not happen.
STEP=code
if [ "$PULL_STATE" = ok ]; then
  CODE_STATE=pull-ok
elif [ "$SRC" = "$BUILD" ]; then
  # Invoked as $BUILD's own copy — there is no fresher source to hand over.
  CODE_STATE=no-source
elif ! git -C "$SRC" rev-parse --short HEAD >/dev/null 2>&1; then
  CODE_STATE=no-source
elif ! ( cd "$SRC" && python3 -m py_compile build_seo.py seo_guides.py ) 2>/dev/null; then
  # Source is present but broken. Leave $BUILD alone and say so loudly enough
  # that the morning review sees a named cause instead of an unexplained freeze.
  CODE_STATE=skipped-compile
  echo "refresh_seo: $SRC/build_seo.py does not compile — kept $BUILD's copy"
else
  n=0
  # build_landlords.py is NOT in this list on purpose: it needs a Supabase token
  # the droplet does not hold, so landlords.json is generated on a workstation
  # and carried in like the source files. hpd_contacts.json is here because
  # build_seo.py started reading it for the owner block on every building page,
  # and $BUILD had no copy at all.
  for f in build_seo.py seo_guides.py split_hpd.py landlords.json hpd_contacts.json; do
    if [ -f "$SRC/$f" ] && ! cmp -s "$SRC/$f" "$BUILD/$f"; then
      # `cp && n=…` as the last statement of the loop body would take the whole
      # script out under `set -e` if the copy ever failed on permissions.
      if cp -f "$SRC/$f" "$BUILD/$f"; then n=$((n + 1)); fi
    fi
  done
  if [ "$n" -gt 0 ]; then CODE_STATE="synced-$n"; else CODE_STATE=in-sync; fi
  echo "refresh_seo: code $CODE_STATE (from $SRC at $(git -C "$SRC" rev-parse --short HEAD 2>/dev/null || echo '?'))"
fi
status code

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
# Split the boot payload. buildings.min.json is 2.12 MB gzipped and the whole of
# it is parsed before the map draws a pin; half of that is HPD detail only the
# building sheet reads. split_hpd.py writes buildings.slim.json (what the app
# boots from) and buildings.hpd.json (fetched on the first detail open) beside
# it. Non-fatal, and the app falls back to buildings.min.json if either is
# missing, so a failure here degrades to today's behaviour rather than an outage.
STEP=split
if [ -f "$BUILD/split_hpd.py" ]; then
  python3 "$BUILD/split_hpd.py" --docroot "$DOC" || echo "refresh_seo: split_hpd failed — app falls back to buildings.min.json"
else
  echo "refresh_seo: no split_hpd.py in $BUILD — skipping payload split"
fi
status split

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
