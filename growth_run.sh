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
git add -A growth/techniques.json growth/keywords.json growth/results.jsonl \
           growth/journal.md growth/last_run.json growth/gsc_pages.json \
           "$BEAT" 2>/dev/null
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
