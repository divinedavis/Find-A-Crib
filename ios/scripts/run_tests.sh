#!/usr/bin/env bash
# Unit + UI tests on a booted simulator. `bootstatus -b` first — a cold-booting
# sim fails XCUITest preflight with "Busy" (reference_ios_sim_busy_preflight).
set -euo pipefail
cd "$(dirname "$0")/.."
SIMULATOR_ID="${SIMULATOR_ID:-$(xcrun simctl list devices available -j | python3 -c "import json,sys;d=json.load(sys.stdin);print(next(iter([dev['udid'] for r in d['devices'].values() for dev in r if dev.get('state')=='Booted' and 'iPhone' in dev.get('name','')] + [dev['udid'] for r in d['devices'].values() for dev in r if 'iPhone' in dev.get('name','') and dev.get('isAvailable')]), ''))")}"
xcrun simctl boot "$SIMULATOR_ID" 2>/dev/null || true
xcrun simctl bootstatus "$SIMULATOR_ID" -b >/dev/null 2>&1 || true
# Start from a fresh install. Notification permission survives an in-place
# reinstall, so one run (or a manual repro) that tapped Allow leaves every
# later run with the launch card gone and the Push alerts row reading
# "allowed" — two tests fail on state, not code (2026-09-19).
xcrun simctl uninstall "$SIMULATOR_ID" com.divinedavis.findacrib 2>/dev/null || true
ONLY="${1:-}"
# The whole run goes to a file and only the last 60 lines are printed: a
# failure earlier than that was invisible twice in one afternoon (2026-09-23),
# costing a full re-run to find out which test it was. Now every failing line
# is printed after the tail, and the full log stays on disk.
LOG="build.nosync/test-$SIMULATOR_ID.log"
mkdir -p build.nosync
set +e
xcodebuild -project FindACrib.xcodeproj -scheme FindACrib \
  -destination "platform=iOS Simulator,id=$SIMULATOR_ID" -derivedDataPath build.nosync/tests \
  ${ONLY:+-only-testing:"$ONLY"} test 2>&1 | grep -E "Test Suite|Test Case|error:|failed|passed|\*\* TEST" > "$LOG"
status=${PIPESTATUS[0]}
set -e
tail -60 "$LOG"
if [ "$status" -ne 0 ]; then
  echo "---- every failure in this run ($LOG) ----"
  grep -E "error:|' failed \(" "$LOG" || true
fi
exit "$status"
