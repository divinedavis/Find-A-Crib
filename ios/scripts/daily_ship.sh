#!/usr/bin/env bash
# One Find A Crib TestFlight build a day (owner, 2026-10-21: "bundle the
# builds and ship once a day for this app and fac"). launchd
# com.findacrib.daily-ship runs this at 03:05 (scripts/install_daily_ship.sh),
# from its own worktree, ~/projects/dhcr-map-daily, kept on origin/main and
# used by nothing else, so no session's uncommitted work is ever shipped.
# Sessions merge finished iOS work to main during the day and don't ship it.
#
#   1. nothing to do unless main has iOS app changes since the last
#      "iOS: build N" commit;
#   2. a start after 09:00 (the Mac slept through 03:05) waits for tonight;
#   3. waits for any other build or ship on this Mac (one at a time), until 09:00;
#   4. runs scripts/ship.sh (iPhone + iPad suites, perf gate, upload), which
#      commits and pushes the bump to main itself.
# Failures notify and land in ios/build.nosync/daily-ship.log.
#
#   scripts/daily_ship.sh [--dry-run]     (DAILY_SHIP_NOW=1: run after 09:00 too)
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
APP_PATHS=(FindACrib FindACribTests FindACribUITests FindACribWidgets Shared project.yml)
DRY=0; [[ "${1:-}" == "--dry-run" ]] && DRY=1
mkdir -p build.nosync

say() { echo "$(date '+%F %T') $1"; }
notify() {
    say "$1"
    osascript -e "display notification \"$1 (ios/build.nosync/daily-ship.log)\" with title \"Find A Crib daily build\"" 2>/dev/null || true
}
# Any other project's or session's build. Bracketed patterns so this script
# never matches itself.
busy() { ps -axo command | grep -qE "[x]codebuild (test|archive|build|-)|[s]cripts/ship\.sh|[a]ltool --upload"; }
past_cutoff() { (( 10#$(date +%H) >= 9 )); }

say "=== daily build"
if past_cutoff && [[ "${DAILY_SHIP_NOW:-0}" != "1" ]]; then
    notify "the Mac was asleep at 03:05; today's changes ship tonight"; exit 0
fi
git fetch -q origin
# A ship whose bump didn't push leaves a commit here: send it before moving on,
# or the next build would reuse its number.
if [[ -n "$(git log --oneline origin/main..HEAD)" ]]; then
    git rebase -q origin/main && git push -q origin HEAD:main || { notify "an earlier build's bump won't push; skipped"; exit 1; }
fi
git reset -q --hard && git checkout -q --detach origin/main

last=$(git log -1 --format=%H --grep='^iOS: build [0-9]' origin/main)
changes=$(git log --format='- %s' --no-merges "$last"..HEAD -- "${APP_PATHS[@]}" | grep -vE '^- iOS: build [0-9]' || true)
if [[ -z "$changes" ]]; then say "no iOS app changes since $(git log -1 --format=%h "$last"); nothing to ship"; exit 0; fi
say "iOS app changes since the last build:"; echo "$changes"
(( DRY )) && { say "dry run: would ship"; exit 0; }

while busy; do
    past_cutoff && { notify "no build today: another build kept the Mac busy"; exit 1; }
    sleep 300
done

./scripts/ship.sh || { notify "ship failed; see ios/build.nosync/daily-ship.log"; exit 1; }
notify "build $(grep -m1 'CURRENT_PROJECT_VERSION:' project.yml | sed -E 's/.*"([0-9]+)".*/\1/') is on its way to TestFlight"
