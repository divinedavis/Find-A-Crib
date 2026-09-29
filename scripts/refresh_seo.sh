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
DATA_STATE=pending    # …and the nightly feeds: see STEP=data
VOUCHER_H=null        # age in hours of the s8.json build_seo.py will actually read
# The IndexNow submission's own outcome. This step ships the BULK of the
# channel — 4,047 URLs on 2026-09-29 against the 6 growth's t_indexnow sends —
# and until now it reported nothing at all: its python caught every exception,
# printed to a stdout the cron discards, and returned success either way. A key
# Bing had revoked would have looked exactly like a clean submission, for as
# long as it took somebody to notice by other means, and nobody could have.
# A word from a closed set, never captured output: see the header's rule.
#   pending         never reached — the script died before STEP=indexnow
#   nothing-changed nothing to submit; the honest no-op, not a failure
#   no-key          $BUILD/indexnow.key missing or empty
#   ok              the endpoint took it (HTTP 2xx)
#   rejected        the endpoint refused it (HTTP 4xx — 403 is a bad/revoked key)
#   failed          no HTTP answer at all (DNS, timeout, TLS, python itself)
# DELIBERATELY NOT an exit code: this step runs AFTER the deploy, so failing the
# script here would report a night that published 49,383 pages as a failed run,
# and a transient timeout would do it. The verdict goes in the field, and
# growth/techniques.py turns a bad one into a RED audit line the 6am review
# reads — which reaches a human sooner than an rc in a heartbeat ever did.
INDEXNOW_STATE=pending
INDEXNOW_N=0          # URLs actually handed to the endpoint
INDEXNOW_HTTP=null    # the HTTP status it answered with, when it answered

status() {
  {
    printf '{"started":"%s","at":"%s","phase":"%s","step":"%s","rc":%s,"head":"%s","changed_urls":%s,"corpus_pages":%s,"pull":"%s","code":"%s","data":"%s","voucher_feed_h":%s,"indexnow":"%s","indexnow_urls":%s,"indexnow_http":%s}\n' \
      "$STARTED" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$STEP" "${2:-null}" \
      "$(git -C "$BUILD" rev-parse --short HEAD 2>/dev/null || echo unknown)" \
      "$CHANGED_N" "$CORPUS_N" "$PULL_STATE" "$CODE_STATE" "$DATA_STATE" "$VOUCHER_H" \
      "$INDEXNOW_STATE" "$INDEXNOW_N" "$INDEXNOW_HTTP" \
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
  # growth/gsc_pages.json added 2026-08-30. build_seo.py's index triage reads it
  # for the ever-served rule -- the one that keeps a page Google is ALREADY
  # showing out of the noindex tier. $BUILD had no copy, so EVER_SERVED_BBLS was
  # empty on every production build since the rule shipped on 08-28, and the
  # rule silently did nothing: 5 of 6 sampled ever-served building pages were
  # live with noindex on them. The fallback in _ever_served_bbls() is
  # deliberately non-fatal, which is why this printed one line and never failed.
  # The three hand-authored HTML pages added 2026-09-13. build_seo.py's
  # stage_static_pages() copies them into $BUILD/seo so the rsync below
  # deploys them, and it reads them from its OWN directory — which is $BUILD.
  # Without them on this list it would stage whatever stale copies the droplet
  # was set up with, which is the same bug growth/gsc_pages.json had. They have
  # no other deploy path: deploy_app.sh scp's index.html, the four city shells
  # and supercluster.min.js, and nothing else. The app shells are deliberately
  # NOT here — deploy_app.sh gates those behind tests/journeys.py.
  for f in build_seo.py seo_guides.py split_hpd.py landlords.json hpd_contacts.json \
           growth/gsc_pages.json \
           developers/index.html embed/index.html marketing-agents/index.html; do
    if [ -f "$SRC/$f" ] && ! cmp -s "$SRC/$f" "$BUILD/$f"; then
      mkdir -p "$BUILD/$(dirname "$f")"
      # `cp && n=…` as the last statement of the loop body would take the whole
      # script out under `set -e` if the copy ever failed on permissions.
      if cp -f "$SRC/$f" "$BUILD/$f"; then n=$((n + 1)); fi
    fi
  done
  if [ "$n" -gt 0 ]; then CODE_STATE="synced-$n"; else CODE_STATE=in-sync; fi
  echo "refresh_seo: code $CODE_STATE (from $SRC at $(git -C "$SRC" rev-parse --short HEAD 2>/dev/null || echo '?'))"
fi
status code

# ------------------------------------------------ hand the nightly feeds over
# The twin of the block above, for data instead of code, and the same "two
# doors" shape: a pipeline reading one copy of something while everything else
# on the box updates another.
#
# build_seo.py reads every feed from ITS OWN directory, which is $BUILD:
# VOUCHER_PATH and load_listings() both join dirname(__file__). The live copies
# are in the docroot. What establishes that, rather than assumes it:
# findacrib.com/s8.json and findacrib.com/listings.json are served from $DOC and
# ios/scripts/refresh_data.sh curls them from the site; api_server.py loads "the
# same files the site serves"; growth's Context._load() looks in the docroot
# FIRST and got a 2026-09-27 s8.json with 288 voucher listings out of it, while
# the git checkout's committed copy is dated 2026-07-11 with 238. Nothing has
# ever copied the docroot's into $BUILD, and $BUILD is not a git worktree either
# ("pull":"no-worktree" every night), so its copies are whatever that directory
# was set up with.
#
# HOW FAR THAT IS PROVEN, because it was diagnosed from a cloud checkout with no
# droplet access: the second incident below is an inference, not a reading. What
# is certain is that the docroot's feed was fresh, that 288 building pages that
# were rebuilt that morning carry the neighbouring comparison block and not the
# voucher badge, and that a >48h feed is the one documented way build_seo.py
# writes the first without the second. voucher_feed_h below settles it either
# way on the first night this runs: a number over 48 confirms it, and a number
# under 48 with the badge still missing moves the fault to the address->page
# join and this block is then a harmless no-op.
#
# What the shape has cost:
#   * 2026-09-19 found 312 building pages calling a unit "recently advertised"
#     off a listings.json last refreshed 2026-05-09. That was read as a pruning
#     bug in the feed. The feed was fine; $BUILD's copy of it was four months old.
#   * 2026-09-24 shipped the voucher badge onto the building tier — the one
#     dataset that changes every night, onto the one tier Google crawls. On
#     2026-09-27 t_voucher_reach read 0 of 288 pages carrying it. load_voucher_
#     listings() suppresses every voucher claim once the feed passes
#     VOUCHER_STALE_HOURS=48 and says so in one line of stdout, which
#     growth_run.sh discards. So the badge rendered nowhere, for the same reason,
#     and the audit built to catch it could not name the cause: it reads the
#     DOCROOT's s8.json (fresh, 288 listings) and the builder reads this one.
#
# Deliberately narrow, and safe under either belief about who writes $BUILD:
#   * ONLY when the docroot's copy is strictly newer (-nt, which is also true
#     when $BUILD has no copy at all). If the scrapes do write into $BUILD, or
#     already ran tonight, every test fails and this is a no-op — it can never
#     make a feed older than it found it, which is the one thing that would
#     turn a stale claim into a false one;
#   * ONE file, named. s8.json is pure input — build_seo.py reads it and writes
#     nothing back — and its consumer fails safe: load_voucher_listings() drops
#     the claim rather than making a wrong one, so the worst a surprise in that
#     file can do is what is already happening.
#     DELIBERATELY NOT listings.json, though it has the identical defect (the
#     2026-09-19 incident above). build_seo.py reads two different keys out of
#     it: `posted` backs the "recently advertised" sentence and `counts` backs
#     SITEMAP PROMOTION via ever_advertised_bbls(). The committed copy carries
#     counts (312 BBLs) and no posted map at all, and nothing in this checkout
#     can say what shape the docroot serves. If its counts map were slimmer,
#     handing it over would de-promote building pages into the noindex tier —
#     a silent, site-wide indexing change — to fix a sentence. Verify the
#     served file's shape against ever_advertised_bbls() first, then add it.
#     Not buildings.min.json either (carried in git, generated on a workstation,
#     and the docroot's copy is a deploy artifact rather than a scrape), and not
#     seo_lastmod.json (per-corpus state — replacing it would bump every lastmod
#     on the site);
#   * a copy, never a move or a delete, and never the reverse direction;
#   * non-fatal at every step, like the heartbeat and the code handover: this
#     must not become the new reason the night's rebuild does not happen.
#
# VOUCHER_H is reported because it is the number the 48h gate is decided on, and
# until now no one off the droplet could see it. A red t_voucher_reach with
# voucher_feed_h=1861 is a diagnosis; the same red with no number is a mystery,
# and it stayed a mystery for three days.
STEP=data
if [ "$DOC" = "$BUILD" ]; then
  DATA_STATE=same-dir
elif [ ! -d "$DOC" ]; then
  DATA_STATE=no-docroot
else
  n=0
  for f in s8.json; do
    if [ -f "$DOC/$f" ] && [ "$DOC/$f" -nt "$BUILD/$f" ]; then
      if cp -pf "$DOC/$f" "$BUILD/$f" 2>/dev/null; then n=$((n + 1)); fi
    fi
  done
  if [ "$n" -gt 0 ]; then DATA_STATE="synced-$n"; else DATA_STATE=in-sync; fi
  echo "refresh_seo: nightly feeds $DATA_STATE (from $DOC)"
fi
# Whatever the handover did or did not do, report the age of the feed the build
# is about to read — from `avail_updated` INSIDE the file, which is the field
# load_voucher_listings() applies VOUCHER_STALE_HOURS to. Not the mtime: a copy
# or a touch moves an mtime without making the data any newer, and this number
# exists to be trusted on the one morning that distinction decides the answer.
# null on a missing, unreadable or undated file, because absent is not the same
# as old and load_voucher_listings() suppresses on all of them alike.
VOUCHER_H=$(python3 -c 'import json,sys,time
try:
    with open(sys.argv[1]) as f: d = json.load(f)
    print(int((time.time() - float(d["avail_updated"])) / 3600))
except Exception:
    print("null")' "$BUILD/s8.json" 2>/dev/null) || VOUCHER_H=null
[ -n "$VOUCHER_H" ] || VOUCHER_H=null
status data

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
# The key read used to be a bare `KEY="$(cat "$BUILD/indexnow.key")"`, which
# under `set -e` killed the whole script when the file was missing — AFTER the
# corpus had already deployed, so a healthy publishing night reported rc=1 and
# nobody could tell from the record what had actually failed. Guarded now, and
# reported in a field instead.
INDEXNOW_KEY=""
if [ -s "$BUILD/indexnow.key" ]; then
  INDEXNOW_KEY="$(tr -d '[:space:]' < "$BUILD/indexnow.key")"
fi
VERDICT="$BUILD/.indexnow-verdict"
rm -f "$VERDICT"
if [ -z "$INDEXNOW_KEY" ]; then
  INDEXNOW_STATE=no-key
  echo "refresh_seo: no IndexNow key at $BUILD/indexnow.key — $CHANGED_N changed URLs went unsubmitted"
elif [ -s "$CHANGED" ]; then
  python3 - "$CHANGED" "$INDEXNOW_KEY" "$VERDICT" <<'PY' || true
import sys, json, urllib.request, urllib.error

urls = [l.strip() for l in open(sys.argv[1]) if l.strip()]
key, verdict = sys.argv[2], sys.argv[3]

def say(state, http="null", n=0):
    """One line, closed vocabulary, for the shell to fold into the status file."""
    try:
        with open(verdict, "w") as f:
            f.write("%s %s %d\n" % (state, http, n))
    except OSError:
        pass  # the shell reads a missing verdict as 'failed', which it would be

if not urls:
    print("IndexNow: nothing changed")
    say("nothing-changed")
    raise SystemExit

# Report what was SENT, not what was in hand. The same cap used to be applied
# silently here while the log line printed len(urls); growth/techniques.py's
# t_indexnow was corrected for exactly this on 2026-08-18 and this copy was not.
sent = urls[:10000]
dropped = len(urls) - len(sent)
payload = {"host": "findacrib.com", "key": key,
           "keyLocation": f"https://findacrib.com/{key}.txt",
           "urlList": sent}
req = urllib.request.Request("https://api.indexnow.org/indexnow",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json; charset=utf-8"})
try:
    r = urllib.request.urlopen(req, timeout=30)
    tail = f" ({dropped} more over the 10,000-URL cap)" if dropped else ""
    print(f"IndexNow: submitted {len(sent)} urls -> HTTP {r.status}{tail}")
    # 2xx is the only acceptance. Anything else that still carried a status line
    # is a refusal we can name, which is the whole point of this record.
    say("ok" if 200 <= r.status < 300 else "rejected", r.status, len(sent))
except urllib.error.HTTPError as e:
    # urlopen RAISES on 4xx/5xx, so the previous `except Exception` swallowed a
    # revoked-key 403 into the same "submit failed" line as a DNS outage. That
    # is the defect this block exists to close: they need different owner
    # actions — rotate the key vs. wait — and looked identical for weeks.
    print(f"IndexNow REJECTED: HTTP {e.code} (403 means the key is bad or revoked)")
    say("rejected", e.code, len(sent))
except Exception as e:
    print("IndexNow submit failed:", e)
    say("failed", "null", len(sent))
PY
  # Parse into scratch names and adopt them only if all three fields are the
  # shape the printf needs. A half-read verdict (no trailing newline, truncated
  # write) left INDEXNOW_N and INDEXNOW_HTTP as empty strings in testing, and
  # printf then emitted `"indexnow_urls":,` — INVALID JSON, which makes
  # _seo_pipeline_status() return None and blinds every OTHER field in this
  # record too. A reporting field must never be able to take the report down.
  V_STATE=""; V_HTTP=""; V_N=""
  if [ -s "$VERDICT" ]; then
    read -r V_STATE V_HTTP V_N < "$VERDICT" || true
  fi
  case "$V_STATE|$V_HTTP|$V_N" in
    nothing-changed\|*|ok\|*|rejected\|*|failed\|*|no-key\|*)
      # state is from the vocabulary; now the two numerics, or null for http
      if [ "$V_N" -eq "$V_N" ] 2>/dev/null && { [ "$V_HTTP" = null ] || [ "$V_HTTP" -eq "$V_HTTP" ] 2>/dev/null; }; then
        INDEXNOW_STATE="$V_STATE"; INDEXNOW_HTTP="$V_HTTP"; INDEXNOW_N="$V_N"
      else
        INDEXNOW_STATE=failed
      fi
      ;;
    *)
      # no verdict, or one this script does not recognise — python never got far
      # enough to answer, which is itself a failed submission
      INDEXNOW_STATE=failed
      ;;
  esac
  rm -f "$VERDICT"
else
  INDEXNOW_STATE=nothing-changed
  echo "IndexNow: no changed pages this run"
fi
status indexnow

STEP=done
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] refresh complete: $CORPUS_N pages built, $CHANGED_N changed"
