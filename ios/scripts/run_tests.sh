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
# iPad's minimized (floating) keyboard — which iPadOS turns on once a hardware
# keyboard has been seen — floats over the app and swallows every tap in the
# view under it: with it on, EVERY control in the price sheet read as not
# hittable and a coordinate tap did nothing. Two price tests failed on one iPad
# simulator and passed on another of the same model because of this one
# preference (2026-09-23). Dock the keyboard so every run types against the
# same one.
xcrun simctl spawn "$SIMULATOR_ID" defaults write com.apple.keyboard.preferences \
  AutomaticMinimizationEnabled -bool false >/dev/null 2>&1 || true
# Arguments: test ids for -only-testing (one or more, e.g. the quick first pass
# from changed_tests.py); none = everything.
ONLY_FLAGS=(); for o in "$@"; do ONLY_FLAGS+=(-only-testing:"$o"); done
# SKIP="Target/Class ..." skips those tests (ship.sh keeps the performance
# tests out of the regular passes); RESULT_BUNDLE=path keeps the .xcresult for
# scripts that read it (perf_gate.py).
SKIP_FLAGS=(); for s in ${SKIP:-}; do SKIP_FLAGS+=(-skip-testing:"$s"); done
# RETRY=1 gives a FAILED test one more run (only the failures re-run; a pass
# is still required). 2026-10-16: four ship attempts in a row died on a
# different UI test each time ("Timed out while evaluating UI query",
# "synthesizing event") while another session's simulator tests shared the
# Mac; every one passed alone in seconds. Retried tests are listed below.
RETRY_FLAGS=(); [[ "${RETRY:-0}" == "1" ]] && RETRY_FLAGS=(-retry-tests-on-failure -test-iterations 2)
RESULT_FLAGS=(); [[ -n "${RESULT_BUNDLE:-}" ]] && { rm -rf "$RESULT_BUNDLE"; RESULT_FLAGS=(-resultBundlePath "$RESULT_BUNDLE"); }
# The whole run goes to a file and only the last 60 lines are printed: a
# failure earlier than that was invisible twice in one afternoon (2026-09-23),
# costing a full re-run to find out which test it was. Now every failing line
# is printed after the tail, and the full log stays on disk.
LOG="build.nosync/test-$SIMULATOR_ID.log"
mkdir -p build.nosync
# XCTESTRUN=path (ship.sh sets it after one build-for-testing): run the
# already-built tests on this simulator, no compile step at all. Without it,
# build and test as before, with the shared caches in build_flags.sh.
source scripts/build_flags.sh
if [[ -n "${XCTESTRUN:-}" ]]; then
  ACTION=(-xctestrun "$XCTESTRUN" test-without-building)
else
  ACTION=(-project FindACrib.xcodeproj -scheme FindACrib -derivedDataPath build.nosync/tests "${FAST_FLAGS[@]}" test)
fi
set +e
xcodebuild -destination "platform=iOS Simulator,id=$SIMULATOR_ID" \
  ${ONLY_FLAGS[@]+"${ONLY_FLAGS[@]}"} ${SKIP_FLAGS[@]+"${SKIP_FLAGS[@]}"} ${RESULT_FLAGS[@]+"${RESULT_FLAGS[@]}"} ${RETRY_FLAGS[@]+"${RETRY_FLAGS[@]}"} "${ACTION[@]}" > "$LOG.raw" 2>&1
status=$?
grep -E "Test Suite|Test Case|error:|failed|passed|\*\* TEST" "$LOG.raw" > "$LOG" || true
set -e
tail -60 "$LOG"
if [[ "${RETRY:-0}" == "1" ]] && grep -qE "' failed \(" "$LOG"; then
  echo "---- failed once, then re-run (flaky under load?) ----"
  grep -E "' failed \(" "$LOG" | sort -u || true
fi
if [ "$status" -ne 0 ]; then
  echo "---- every failure in this run ($LOG) ----"
  grep -E "error:|' failed \(" "$LOG" || true
  # A failure's message often runs over several lines (the accessibility audit
  # lists one issue per line) and the filtered log keeps only the first, so
  # build 153's "Results: 1 accessibility issue(s)" arrived with no issue and
  # needed a separate run to read (2026-10-21). Print each one whole.
  echo "---- failure details ----"
  awk '/: error: /{n=12} n&&!/^ *t = /{print; n--}' "$LOG.raw" | grep -v "coretelephony" | head -120 || true
fi
# One simulator at a time (2026-10-21: a ship was killed for low memory on this
# 16 GB Mac). ship.sh sets SHUTDOWN_AFTER=1 so each pass frees its simulator
# before the next boots one; the global close-simulators hook is the backstop.
[[ "${SHUTDOWN_AFTER:-0}" == "1" ]] && xcrun simctl shutdown "$SIMULATOR_ID" 2>/dev/null || true
exit "$status"
