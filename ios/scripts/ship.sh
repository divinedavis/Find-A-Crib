#!/usr/bin/env bash
# Find A Crib — test, smoke-launch, bump build, archive, export, upload to
# TestFlight. Build number lives in project.yml (CURRENT_PROJECT_VERSION)
# because the pbxproj is generated. Every ship runs the full suite on iPhone and
# iPad (see "running every test" below).
set -euo pipefail
cd "$(dirname "$0")/.."
# Owner's App Store freeze (2026-09-21, narrowed the same day): TestFlight
# uploads are fine, the App Store is not. While ASC_FREEZE exists this script
# still builds and uploads, but never attaches the build to an App Store
# version. Delete ASC_FREEZE only on the owner's word.
[[ -f scripts/asc-config.env ]] || { echo "error: scripts/asc-config.env missing (copy .example)" >&2; exit 1; }
# shellcheck disable=SC1091
source scripts/asc-config.env

# One build at a time on this Mac (scripts/build_lock.sh); under
# daily_ship.sh the lock is already ours.
source scripts/build_lock.sh
build_lock_take "Find A Crib ship.sh"

PROJECT="FindACrib.xcodeproj"; SCHEME="FindACrib"; PROJECT_YML="project.yml"
ARCHIVE="build.nosync/FindACrib.xcarchive"; EXPORT_DIR="build.nosync/export"; IPA="$EXPORT_DIR/FindACrib.ipa"

echo "==> $(date +%T) refreshing seed data"
./scripts/refresh_data.sh >/dev/null

# The project is generated: a resource added since the last generate is not
# in the bundle until it runs again. hcr.json shipped as a no-op once because
# the regenerate only happened at the bump step, after the tests.
echo "==> $(date +%T) regenerating xcodeproj"
./scripts/generate.sh >/dev/null

# Apple's four quality checks run before every TestFlight upload (owner,
# 2026-10-02), and follow the app as features are added and removed:
#   1. Swift Testing — the @Test suites in FindACribTests run with the unit
#      tests; the run must report at least one Swift Testing test.
#   2. XCUITest + performAccessibilityAudit — AccessibilityAuditTests walks
#      every tab it finds at run time, plus results and detail, on iPhone + iPad.
#   3. XCTMetric performance — PerformanceTests on the iPhone, judged by
#      perf_gate.py against a baseline that moves with the last 5 ships.
#   4. MetricKit + Xcode Organizer — the subscriber must still be wired, and the
#      Organizer's field numbers for recent builds are printed (report only).
# check_test_coverage.py fails a feature folder no UI test touches, or a UI
# test still waiting for an identifier the app no longer has.
echo "==> $(date +%T) UI test coverage follows the features"
python3 scripts/check_test_coverage.py
# Every translation consumes the same format arguments as its English
# (a mismatch crashes String(format:) at run time), plurals have "other",
# and "Find A Crib" is never translated away (2026-10-16, Spanish, Chinese,
# Korean; see scripts/l10n/).
echo "==> $(date +%T) translations safe in every language"
python3 -c "import sys; sys.path.insert(0, 'scripts'); import test_localizable_catalog as t; [getattr(t, n)() for n in dir(t) if n.startswith('test_')]"
echo "==> $(date +%T) quick-pass test picker"
python3 scripts/test_changed_tests.py >/dev/null
echo "==> $(date +%T) MetricKit still wired (metrics + crash/hang diagnostics)"
for want in "MXMetricManager.shared.add" "didReceive(_ payloads: \[MXMetricPayload\])" "didReceive(_ payloads: \[MXDiagnosticPayload\])"; do
  grep -rq "$want" FindACrib/Services/Metrics.swift || { echo "error: Metrics.swift lost: $want" >&2; exit 1; }
done
grep -rq "Metrics.shared.start()" FindACrib/App || { echo "error: Metrics.shared.start() is no longer called at launch" >&2; exit 1; }

# Every ship runs the FULL suite — unit tests and every XCUITest journey — on
# an iPhone AND on an iPad (owner, 2026-09-22: "make sure the ipad goes through
# a robust set of journeys and xcuitests"). The iPad pass includes
# IPadTourTests, which walks every screen in both orientations; the tour runs
# again on an iPad mini, the narrowest iPad, where the results bar has the
# least room. Any failure stops the ship (run_tests.sh is set -o pipefail).
# SHIP_UNIT_ONLY=1 is the escape hatch for an emergency ship; say why.
sim_named() {   # first available simulator whose name contains $1
  xcrun simctl list devices available -j | python3 -c "import json,sys
d=json.load(sys.stdin)
print(next(iter([v['udid'] for r in d['devices'].values() for v in r if v.get('name','').startswith(sys.argv[1])]), ''))" "$1"
}
# "FAC iPhone" is Find A Crib's own (2026-10-04), like "FAC iPad": a shared
# "iPhone 17 Pro" can have another session's app launched over ours mid-test.
IPHONE_SIM="${SIMULATOR_ID:-$(sim_named 'FAC iPhone')}"; [[ -n "$IPHONE_SIM" ]] || IPHONE_SIM=$(sim_named 'iPhone 17 Pro'); [[ -n "$IPHONE_SIM" ]] || IPHONE_SIM=$(sim_named 'iPhone')
# "FAC iPad" is Find A Crib's own (2026-10-03): on the shared "iPad Pro
# 11-inch" another session's Hidden Gems tests kept launching their app over
# ours mid-test, failing six iPad tests that pass alone.
IPAD_SIM="${IPAD_SIMULATOR_ID:-$(sim_named 'FAC iPad')}"; [[ -n "$IPAD_SIM" ]] || IPAD_SIM=$(sim_named 'iPad Pro 11-inch'); [[ -n "$IPAD_SIM" ]] || IPAD_SIM=$(sim_named 'iPad')
MINI_SIM="${MINI_SIMULATOR_ID:-$(sim_named 'iPad mini')}"
# Build once for every simulator (generic destination), then every pass below
# runs those same binaries with test-without-building: the iPhone, iPad,
# iPad mini and performance passes and both smoke launches used to compile
# five more times between them (owner, 2026-10-18).
# Measure on a quiet Mac, and measure twice before failing: build 153's
# launch read 2.05 s vs 0.91 s while another session's build had the load
# average at ~90 (2026-10-21), a Mac problem and not an app one. A real
# regression fails both runs.
perf_run() {
  echo "==> $(date +%T) waiting for a quiet Mac + simulator"; SIM_UDID="$IPHONE_SIM" ./scripts/wait_sim_quiet.sh 900
  echo "==> $(date +%T) performance tests on iPhone ($IPHONE_SIM)$1"
  RESULT_BUNDLE=build.nosync/perf.xcresult SIMULATOR_ID="$IPHONE_SIM" ./scripts/run_tests.sh FindACribUITests/PerformanceTests
}
perf_gate_run() {
  # A rehearsal judges against the baseline but doesn't move it.
  local rec=(--record); [[ "${SHIP_REHEARSAL:-0}" == "1" ]] && rec=()
  perf_run ""
  if ! python3 scripts/perf_gate.py build.nosync/perf.xcresult ${rec[@]+"${rec[@]}"}; then
    perf_run " — second measurement before failing"
    python3 scripts/perf_gate.py build.nosync/perf.xcresult ${rec[@]+"${rec[@]}"}
  fi
}
# Flaky-test quarantine (owner, 2026-10-24): tests listed in
# scripts/quarantine.txt are skipped in the blocking passes and run once,
# non-blocking, afterwards. The owner approves every entry.
QUARANTINE_IDS=(); while IFS= read -r t; do QUARANTINE_IDS+=("$t"); done < <(grep -vE '^\s*(#|$)' scripts/quarantine.txt 2>/dev/null | awk '{print $1}')
QUARANTINE="${QUARANTINE_IDS[*]:-}"

echo "==> $(date +%T) building the app and tests once"
source scripts/build_flags.sh
mkdir -p build.nosync   # a fresh worktree has none; the log below needs it
rm -rf build.nosync/tests/Build/Products/*.xctestrun
xcodebuild -project "$PROJECT" -scheme "$SCHEME" -destination "generic/platform=iOS Simulator" \
  -derivedDataPath build.nosync/tests "${FAST_FLAGS[@]}" build-for-testing > build.nosync/build-for-testing.log 2>&1 \
  || { echo "error: build-for-testing failed" >&2; grep -E "error:" build.nosync/build-for-testing.log | head -20 >&2; exit 1; }
XCTESTRUN=$(ls build.nosync/tests/Build/Products/*.xctestrun | head -1); export XCTESTRUN
SMOKE_APP=$(ls -d build.nosync/tests/Build/Products/Debug-iphonesimulator/FindACrib.app); export SMOKE_APP
if [[ "${SHIP_UNIT_ONLY:-0}" == "1" ]]; then
  echo "==> $(date +%T) SHIP_UNIT_ONLY: unit tests only on iPhone (no XCUITest, no iPad)"
  SIMULATOR_ID="$IPHONE_SIM" ./scripts/run_tests.sh FindACribTests
else
  # Quick pass first: unit tests, the accessibility audit and the UI tests
  # that touch what changed since the last ship, so a likely failure shows in
  # minutes instead of 17-20 in (build 153 failed that late twice, 2026-10-21).
  QUICK=(); while IFS= read -r t; do QUICK+=("$t"); done < <(python3 scripts/changed_tests.py)
  echo "==> $(date +%T) quick pass on iPhone: ${#QUICK[@]} groups most likely to fail on this change"
  RETRY=1 SKIP="$QUARANTINE" SIMULATOR_ID="$IPHONE_SIM" ./scripts/run_tests.sh "${QUICK[@]}"
  echo "==> $(date +%T) running every test on iPhone ($IPHONE_SIM)"
  RETRY=1 SKIP="FindACribUITests/PerformanceTests $QUARANTINE" SIMULATOR_ID="$IPHONE_SIM" ./scripts/run_tests.sh
  grep -qE "Test run with [1-9][0-9]* tests? .*passed" "build.nosync/test-$IPHONE_SIM.log" \
    || { echo "error: no Swift Testing tests ran (expected the @Test suites in FindACribTests)" >&2; exit 1; }
  grep -q "AccessibilityAuditTests" "build.nosync/test-$IPHONE_SIM.log" \
    || { echo "error: the accessibility audit did not run" >&2; exit 1; }
  [[ -n "$IPAD_SIM" ]] || { echo "error: no iPad simulator installed — the iPad gate cannot run" >&2; exit 1; }
  # Performance next, on the iPhone simulator the full pass just warmed
  # (2026-10-24): measuring after the iPad passes meant booting it again and
  # waiting ~3 min for the fresh boot to settle. The quiet check stays; on a
  # warm simulator it passes in about 30 s.
  perf_gate_run
  xcrun simctl shutdown "$IPHONE_SIM" 2>/dev/null || true
  echo "==> $(date +%T) running every test on iPad ($IPAD_SIM)"
  RETRY=1 SHUTDOWN_AFTER=1 SKIP="FindACribUITests/PerformanceTests $QUARANTINE" SIMULATOR_ID="$IPAD_SIM" ./scripts/run_tests.sh
  if [[ -n "$MINI_SIM" ]]; then
    echo "==> $(date +%T) iPad tour on iPad mini ($MINI_SIM)"
    SHUTDOWN_AFTER=1 SIMULATOR_ID="$MINI_SIM" ./scripts/run_tests.sh FindACribUITests/IPadTourTests
  fi
fi

if [[ "${SHIP_UNIT_ONLY:-0}" != "1" && ${#QUARANTINE_IDS[@]} -gt 0 ]]; then
  # Quarantined tests still run, on the iPhone, but don't stop the ship
  # until they're fixed and taken off the list (scripts/quarantine.txt).
  echo "==> $(date +%T) quarantined tests (not blocking): ${QUARANTINE_IDS[*]}"
  SHUTDOWN_AFTER=1 SIMULATOR_ID="$IPHONE_SIM" ./scripts/run_tests.sh "${QUARANTINE_IDS[@]}" \
    || echo "warning: a quarantined test failed (not blocking): see build.nosync/test-$IPHONE_SIM.log"
fi
echo "==> $(date +%T) Xcode Organizer: what real phones reported for recent builds"
"${PY:-$HOME/.venvs/spendcap/bin/python}" scripts/organizer_report.py || echo "warning: Organizer report unavailable (App Store Connect API)"

if [[ "${SHIP_SKIP_SMOKE:-0}" == "1" ]]; then echo "==> $(date +%T) skipping smoke test"; else
  # One sim at a time: shut each smoke sim before booting the next.
  echo "==> $(date +%T) smoke-testing a launch on iPhone"; SIMULATOR_ID="$IPHONE_SIM" ./scripts/smoke_test.sh
  xcrun simctl shutdown "$IPHONE_SIM" 2>/dev/null || true
  echo "==> $(date +%T) smoke-testing a launch on iPad"; SIMULATOR_ID="$IPAD_SIM" ./scripts/smoke_test.sh
  xcrun simctl shutdown "$IPAD_SIM" 2>/dev/null || true
fi

# SHIP_REHEARSAL=1: everything up to here (every test pass, the perf gate,
# the smoke launches), then stop: no bump, archive or upload. For timing and
# trying pipeline changes without sending a build to TestFlight.
if [[ "${SHIP_REHEARSAL:-0}" == "1" ]]; then echo "==> $(date +%T) rehearsal: stopping before the bump (nothing archived or uploaded)"; exit 0; fi

current=$(grep -m1 'CURRENT_PROJECT_VERSION:' "$PROJECT_YML" | sed -E 's/.*"([0-9]+)".*/\1/')
next=$((current + 1))
echo "==> $(date +%T) bumping build $current -> $next"
sed -i '' "s/CURRENT_PROJECT_VERSION: \"$current\"/CURRENT_PROJECT_VERSION: \"$next\"/" "$PROJECT_YML"
./scripts/generate.sh >/dev/null

ASC_AUTH_FLAGS=(-authenticationKeyPath "$ASC_KEY_PATH" -authenticationKeyID "$ASC_KEY_ID" -authenticationKeyIssuerID "$ASC_ISSUER_ID")

echo "==> $(date +%T) archiving"
rm -rf "$ARCHIVE" "$EXPORT_DIR"
# DEVELOPMENT_TEAM is in project.yml, but pass it anyway: automatic signing
# without a team fails with "requires a development team".
xcodebuild -project "$PROJECT" -scheme "$SCHEME" -configuration Release \
  -destination "generic/platform=iOS" -archivePath "$ARCHIVE" \
  -allowProvisioningUpdates "${ASC_AUTH_FLAGS[@]}" DEVELOPMENT_TEAM="$ASC_TEAM_ID" archive > build.nosync/archive.log 2>&1 \
  || { echo "error: archive failed" >&2; grep -E "error" build.nosync/archive.log | tail -20 >&2; exit 1; }
[[ -d "$ARCHIVE" ]] || { echo "error: archive missing" >&2; tail -30 build.nosync/archive.log >&2; exit 1; }

echo "==> $(date +%T) exporting IPA"
# Apple's tools first (2026-10-12): Xcode's IPA step runs /usr/bin/rsync, which
# starts the rsync it finds on PATH for the receiving side. A Homebrew rsync
# 3.x there rejects Apple's --extended-attributes and the export dies with
# just "Copy failed".
PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH" xcodebuild -exportArchive -archivePath "$ARCHIVE" -exportPath "$EXPORT_DIR" \
  -exportOptionsPlist ExportOptions.plist -allowProvisioningUpdates "${ASC_AUTH_FLAGS[@]}" > build.nosync/export.log 2>&1 \
  || { echo "error: export failed" >&2; grep -iE "error" build.nosync/export.log | tail -20 >&2; exit 1; }
# The export names the IPA after CFBundleName ("Find A Crib.ipa"), not the
# product name — find it rather than guess it.
IPA=$(find "$EXPORT_DIR" -maxdepth 1 -name '*.ipa' | head -1)
[[ -n "$IPA" && -f "$IPA" ]] || { echo "error: IPA missing" >&2; tail -30 build.nosync/export.log >&2; exit 1; }

echo "==> $(date +%T) uploading to TestFlight"
xcrun altool --upload-app -f "$IPA" -t ios --apiKey "$ASC_KEY_ID" --apiIssuer "$ASC_ISSUER_ID"
echo "==> $(date +%T) shipped build $next"

# Commit what the ship itself changed (2026-10-21): the build bump, the
# regenerated project, the refreshed seed data and the perf baseline used to be
# left uncommitted, and the next rebase onto origin/main had to work around
# them. Only these paths; anything else in the tree is left alone. The push is
# best effort: a rejected or failed push leaves the commit for the next push.
echo "==> $(date +%T) committing the ship's own changes (build $next)"
SHIP_PATHS=(project.yml FindACrib.xcodeproj FindACrib/Resources/Data scripts/perf_baseline.json)
if [[ -n "$(git status --porcelain -- "${SHIP_PATHS[@]}")" ]]; then
  git add -- "${SHIP_PATHS[@]}"
  if git commit -q -m "iOS: build $next (seed data, perf baseline)" \
       -m "Committed by ship.sh after the TestFlight upload." \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- "${SHIP_PATHS[@]}"; then
    git push -q origin HEAD:main 2>&1 | tail -2 || echo "warning: build $next commit not pushed; push it by hand"
  else
    echo "warning: could not commit build $next's changes; commit them by hand"
  fi
fi

echo "==> $(date +%T) verifying internal tester auto-distribution"
"${PY:-$HOME/.venvs/spendcap/bin/python}" scripts/configure_internal_testers.py || echo "warning: configure_internal_testers.py reported a problem"

# ASC draws the app's header icon from the build attached to the App Store
# VERSION, not from the latest TestFlight upload; attach the newest processed
# build (never submits). Fresh uploads take minutes to process, so a
# "nothing to attach yet" here is normal right after a ship.
if [[ -f ASC_FREEZE ]]; then
  echo "==> $(date +%T) App Store frozen (ios/ASC_FREEZE): TestFlight only, build not attached to any App Store version"
else
  echo "==> $(date +%T) attaching newest processed build to the App Store version"
  "${PY:-$HOME/.venvs/spendcap/bin/python}" scripts/attach_build.py || echo "warning: attach_build.py reported a problem (re-run once the build has processed)"
fi
