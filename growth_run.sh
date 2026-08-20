#!/bin/bash
# Wrapper for the growth engine crons.
#
# The daily review agent runs in Anthropic's cloud with only a git checkout — no
# droplet access. So git IS the channel between it and production: it pushes
# ledger and code changes, and this script pulls them in before each run and
# pushes the night's measurements back out.
#
# Because git is the only channel, silence in git is the only symptom the review
# agent ever sees, and silence has three very different causes: the cron never
# fired, it fired and the run crashed, or it ran fine and the push was lost.
# Those need three different fixes and the review loop has already burned a
# cycle guessing between them (2026-08-09). So this script appends a heartbeat
# record to growth/cron_heartbeat.jsonl before it does anything else and again
# when it finishes, and commits that file whether or not the run succeeded.
# One invariant follows, and it is the whole point: EVERY INVOCATION LEAVES A
# COMMIT. No commit for a morning therefore means the script did not run at all
# — cron, the host, or the checkout — and never means "it ran but stayed quiet".
set -uo pipefail
cd /root/Find-A-Crib || exit 1
export GROWTH_DOCROOT=/var/www/rent-map
set -a; . ./growth.env; set +a

BEAT=growth/cron_heartbeat.jsonl
BEAT_KEEP=200          # ~50 days at two crons a day
JOB="${*:-daily}"

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
head_sha() { git rev-parse --short HEAD 2>/dev/null || echo unknown; }

# Escape for a JSON string: backslashes, quotes, then flatten every control
# character. Written in sed/tr rather than python because a heartbeat whose
# whole job is to report "python did not start" cannot need python to be written.
jesc() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr -d '\000-\037'; }

# beat <phase> <rc> <pull-state> <note>
beat() {
  printf '{"at":"%s","job":"%s","phase":"%s","rc":%s,"pull":"%s","head":"%s","note":"%s"}\n' \
    "$(now)" "$(jesc "$JOB")" "$1" "${2:-null}" "$(jesc "$3")" "$(head_sha)" "$(jesc "${4:-}")" \
    >> "$BEAT" 2>/dev/null
}

beat start null pending ""

# Take whatever the review agent pushed. --autostash so uncommitted ledger
# writes from a previous run never block the pull.
pull_state=ok
git pull --rebase --autostash -q origin main || {
  pull_state=failed
  echo "growth_run: git pull failed, running on the local copy"
}

# A failed pull can leave the checkout in a state that breaks every LATER run
# too, not just this one: an autostash pop that could not be replayed, or an
# interrupted rebase, writes conflict markers into the working tree, and
# ledger.load_techniques() raises SystemExit on the first '<<<<<<<' it reads.
# That is a permanent wedge — nothing later in the day clears it — so recover
# here instead. Ledger files are safe to take from origin/main: the droplet is
# their only writer and pushes them every run, so origin is its own last-known-
# good copy, and this run is about to regenerate them anyway.
if [ -n "$(git ls-files -u 2>/dev/null)" ] || [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then
  conflicted=$(git ls-files -u 2>/dev/null | awk '{print $4}' | sort -u | tr '\n' ' ')
  git rebase --abort >/dev/null 2>&1
  git fetch -q origin main >/dev/null 2>&1
  # shellcheck disable=SC2086 # deliberate word-splitting: one arg per path
  [ -n "$conflicted" ] && git checkout --force FETCH_HEAD -- $conflicted >/dev/null 2>&1
  pull_state="recovered"
  echo "growth_run: recovered a conflicted checkout (${conflicted:-mid-rebase}) from origin/main"
fi

runlog=$(mktemp) || runlog=/tmp/growth_run.$$.log
python3 growth_daily.py "$@" 2>&1 | tee "$runlog"
rc=${PIPESTATUS[0]}

# The tail of the run is what a cloud review needs to tell a crashed run from a
# quiet one, and it is the one thing the droplet's own logs never reach it.
# Only on failure, and only two lines: this file is committed to a public repo,
# and a successful run's output is already summarised in last_run.json.
note=""
if [ "$rc" -ne 0 ]; then
  note=$(grep -v '^[[:space:]]*$' "$runlog" | tail -n 2 | tr '\n' ' ' | cut -c1-300)
fi
rm -f "$runlog"
beat finish "$rc" "$pull_state" "$note"

# ------------------------------------------------------ SEO pipeline watchdog
# scripts/refresh_seo.sh publishes 47,599 of the site's ~47,600 pages from its
# own 04:10 cron. On 2026-08-14 that cron had not deployed since 2026-08-08 and
# had not even STARTED for at least two nights, which is provable two ways:
# build_seo.py's write() rewrites every file unconditionally and sitemap-main.xml
# embeds the build date, so a healthy run gives the docroot's sitemap-*.xml a
# fresh mtime every night even when no page changed — and the .seo-build-status
# heartbeat is written at `status start`, before the pull and before the build,
# so a script that runs and then crashes still leaves the file. Frozen mtime plus
# no status file therefore means "never invoked", not "invoked and failed".
#
# Six days of that stranded every SEO change in git: the browse hubs from 08-09,
# the sibling-link ring from 08-13, and everything after. The review agent runs
# in Anthropic's cloud and cannot touch cron — but THIS script is on the droplet,
# in the right checkout, with the docroot already in the environment, and it
# demonstrably runs every morning. So it can re-run the refresh the missing cron
# owes, which is the difference between the corpus updating nightly and it being
# frozen until someone notices by hand.
#
# Deliberately conservative:
#   * only on the deploy job, never on the measure or scout runs;
#   * only when the corpus is already SEO_STALE_DAYS stale, so a healthy 04:10
#     cron is never raced or duplicated — it wrote at 04:10, we look at 05:40;
#
# SEO_STALE_DAYS went 2 -> 1 on 2026-08-18, and the reason is that the thing it
# was hedging against has not existed for a fortnight. The 04:10 cron has not
# fired since at least 2026-08-14; the watchdog is now the ONLY path by which
# build_seo.py, seo_guides.py or anything else in this repo reaches the 47,600
# published pages. At 2, `find -mtime -2` still matches a sitemap written 48h
# ago, so the watchdog refused to fire two nights out of three and the corpus
# deployed once every THREE days — visible in the heartbeat, which shows
# seo_watchdog_finish on 08-15 and then not again until 08-18. Every content
# change pushed by the review loop sat in git for an average of a day and a half
# waiting for it.
#
# At 1 the anti-race property is exactly as strong: `-mtime -1` matches anything
# written in the last 24h, and a healthy 04:10 cron's sitemaps are 1.5h old when
# this looks at 05:40 — still matched, still skipped. The only slack removed is
# the extra day that was never load-bearing. If the 04:10 cron is ever repaired
# this needs no change; it will simply go back to never firing.
#
# AND ON 2026-08-19 IT STILL DID NOT FIRE, because a threshold in whole days
# cannot express this. The watchdog ran at 05:40:18 on 08-18 and refresh_seo.sh
# finished at 05:41:33. The next night this test ran at 05:40:18 again — 23h
# 58m later — and `-mtime -1` matches anything under 24h, so the sitemaps its
# own previous run had written 1,438 minutes ago still read "fresh" and it stood
# down. It is a fixed daily clock chasing a 24h window by a two-minute margin,
# so it can only ever fire every OTHER night, which is exactly what the
# heartbeat shows: 08-18 yes, 08-19 no. The 2 -> 1 change bought one day of the
# three and the off-by-two-minutes ate the rest. Yesterday's build_seo.py header
# change was still not deployed 24h after it was pushed.
#
# So the threshold is in MINUTES with an explicit guard band. What the test
# actually wants to ask is "was the corpus rebuilt in THIS daily cycle", and
# both crons are on a fixed daily clock, so the honest form is "younger than a
# day minus the width of the window between the two crons". 120 minutes: the
# 04:10 cron's sitemaps are ~90 minutes old when this looks at 05:40, well
# inside 22h and still skipped, and last night's watchdog output at 1,438
# minutes is outside it and correctly reads stale. Every minute of the band is
# margin for a cron that starts late or a build that runs long, and the cost of
# setting it too wide is only that a genuinely healthy pipeline gets a duplicate
# rebuild — which flock already makes safe — while the cost of setting it too
# narrow is the corpus deploying every other day, which is what we just had.
#   * flock, so two watchdogs can never overlap each other;
#   * timeout, so a hung rebuild cannot hold the ledger push hostage;
#   * every failure is swallowed — a watchdog must never be the reason the
#     night's measurements go unpushed. rc is the python run's, and stays so.
#   * GROWTH_SEO_WATCHDOG=0 in growth.env turns it off, for when the pipeline is
#     stopped on purpose.
# It runs the refresh script from THIS checkout, which growth_run.sh has just
# pulled, rather than the copy in $SEO_BUILD. refresh_seo.sh cds to $SEO_BUILD
# and pulls it, so the data and the build dir are the same either way — but the
# script itself is then always the newest version, instead of one night behind
# its own self-pull. Its outcome lands in the heartbeat below, which is committed
# and pushed, so the cloud review reads the result the same morning.
SEO_BUILD=${SEO_BUILD_DIR:-/root/dhcr-build}
SEO_STALE_DAYS=${SEO_STALE_DAYS:-1}
# The guard band, in minutes, subtracted from SEO_STALE_DAYS. See above: whole
# days cannot express "this cycle" for two crons 90 minutes apart on the same
# daily clock, and -mtime's 24h boundary lands two minutes the wrong side of it.
SEO_GUARD_MINS=${SEO_GUARD_MINS:-120}
SEO_FRESH_MINS=${SEO_FRESH_MINS:-$(( SEO_STALE_DAYS * 1440 - SEO_GUARD_MINS ))}
SEO_TIMEOUT=${SEO_WATCHDOG_TIMEOUT:-3600}
SEO_LOCK=${SEO_WATCHDOG_LOCK:-/tmp/findacrib-refresh-seo.lock}

seo_watchdog() {
  [ "${GROWTH_SEO_WATCHDOG:-1}" = "0" ] && return 0
  case "$JOB" in *build*) ;; *) return 0 ;; esac
  [ -d "$SEO_BUILD" ] || return 0
  [ -f ./scripts/refresh_seo.sh ] || return 0
  [ -d "${GROWTH_DOCROOT:-}" ] || return 0

  # Freshness stamps are exactly the sitemaps only build_seo.py writes — the
  # same set as techniques.GROWTH_OWNED_SITEMAPS excludes. sitemap.xml does not
  # match the glob; sitemap-daily.xml does and is the growth build's own, so it
  # is excluded by name. Any new growth-written sitemap-*.xml must be added here
  # too, or this goes blind and stops firing.
  local fresh
  fresh=$(find "$GROWTH_DOCROOT" -maxdepth 1 -name 'sitemap-*.xml' \
            ! -name 'sitemap-daily.xml' -mmin "-$SEO_FRESH_MINS" 2>/dev/null | head -n 1)
  [ -n "$fresh" ] && return 0        # pipeline wrote recently: nothing owed

  local log
  log=$(mktemp) || log=/tmp/seo_watchdog.$$.log
  beat seo_watchdog_start null "$pull_state" "corpus older than ${SEO_FRESH_MINS}min, running scripts/refresh_seo.sh"
  if command -v flock >/dev/null 2>&1; then
    timeout "$SEO_TIMEOUT" flock -n "$SEO_LOCK" bash ./scripts/refresh_seo.sh >"$log" 2>&1
  else
    timeout "$SEO_TIMEOUT" bash ./scripts/refresh_seo.sh >"$log" 2>&1
  fi
  local wrc=$?
  # Two lines, same rule as the run note above: this file is committed to a
  # public repo, and refresh_seo.sh's own .seo-build-status.json carries the
  # real diagnosis. The fallbacks matter — a non-zero rc with NO output is the
  # signature of flock refusing (another copy already running), and reporting
  # that as "ok" would be exactly the "DID NOT RUN — unknown error" mistake of
  # 2026-07-28 in the other direction.
  local wnote=""
  if [ "$wrc" -eq 124 ]; then
    wnote="timed out after ${SEO_TIMEOUT}s"
  elif [ "$wrc" -ne 0 ]; then
    wnote=$(grep -v '^[[:space:]]*$' "$log" | tail -n 2 | tr '\n' ' ' | cut -c1-300)
    wnote=${wnote:-"rc=$wrc with no output — another copy probably holds $SEO_LOCK"}
  else
    wnote="ran refresh_seo.sh to completion"
  fi
  rm -f "$log"
  beat seo_watchdog_finish "$wrc" "$pull_state" "$wnote"

  # The build wrote last_run.json's seo_corpus/seo_pipeline BEFORE the refresh
  # above, and this watchdog only fires when those read stale — so the record
  # about to be committed describes the corpus we just repaired as frozen. That
  # is not a cosmetic lag: last_run.json is what the cloud review is told to
  # trust as ground truth about whether the droplet's pipelines ran, so it was
  # guaranteed to report a dead pipeline on exactly the mornings the watchdog
  # worked. 2026-08-20 is the worked example — heartbeat rc=0 "ran
  # refresh_seo.sh to completion", last_run.json "NO RUN FOR 2.0 DAYS". Re-read
  # the docroot and correct it, and carry the watchdog's own outcome across in
  # the same record. Never fatal: a failure here must not lose the run's commit.
  python3 growth_daily.py seo-status --docroot "$GROWTH_DOCROOT" \
    --watchdog-rc "$wrc" --watchdog-note "$wnote" >/dev/null 2>&1 || \
    echo "growth_run: seo-status restamp failed (rc=$?) — last_run.json still holds the pre-watchdog corpus"
  return 0
}
seo_watchdog || true

# Keep the heartbeat bounded; it is a liveness log, not a record to preserve.
if [ "$(wc -l < "$BEAT" 2>/dev/null || echo 0)" -gt "$BEAT_KEEP" ]; then
  tail -n "$BEAT_KEEP" "$BEAT" > "$BEAT.tmp" && mv "$BEAT.tmp" "$BEAT"
fi

# Push the night's measurements back so the next review can read them.
# gsc_pages.json is here for the same reason last_run.json is: the review agent
# runs on a bare checkout, so a file the droplet writes but never commits is
# invisible to it. This one holds WHICH pages Search Console serves and which
# queries we earn impressions for without tracking them — the difference between
# "77 of 47,600 pages serve" and knowing which 77.
#
# index_status.json is here for exactly the same reason, and was missed when
# indexstatus.py shipped on 2026-08-15: that module's own docstring says "no PII
# — so index_status.json is tracked in git and the cloud review agent can read
# it", which was false for a day, because this allowlist is what makes a file
# tracked and nobody added it. It holds Google's per-URL coverage state for the
# sampled cohort — the difference between "3.1% of the corpus is indexed" and
# knowing whether the other 97% was crawled and declined or never crawled at
# all, which are opposite problems with opposite fixes.
git add -A growth/techniques.json growth/keywords.json growth/results.jsonl \
           growth/journal.md growth/last_run.json growth/gsc_pages.json \
           growth/index_status.json "$BEAT" 2>/dev/null
if ! git diff --cached --quiet; then
  if git commit -q -m "growth: ledger $(date -u +%Y-%m-%d)"; then
    # Retry the push. The operator pushes to this branch by hand at all hours
    # and growth_run.sh had no retry, so a race left the 2026-08-08 ledger
    # commit sitting unpushed on the droplet and the review agent reading
    # day-old numbers with no way to tell why.
    pushed=""
    for attempt in 1 2 3; do
      if git push -q origin main; then pushed=yes; break; fi
      sleep $((attempt * 5))
      git pull --rebase --autostash -q origin main >/dev/null 2>&1
    done
    if [ -n "$pushed" ]; then echo "growth_run: ledger pushed"
    else echo "growth_run: ledger push FAILED after 3 attempts — commit is local"; fi
  fi
fi
exit $rc
