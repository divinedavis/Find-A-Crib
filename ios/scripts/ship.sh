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

PROJECT="FindACrib.xcodeproj"; SCHEME="FindACrib"; PROJECT_YML="project.yml"
ARCHIVE="build.nosync/FindACrib.xcarchive"; EXPORT_DIR="build.nosync/export"; IPA="$EXPORT_DIR/FindACrib.ipa"

echo "==> refreshing seed data"
./scripts/refresh_data.sh >/dev/null

# The project is generated: a resource added since the last generate is not
# in the bundle until it runs again. hcr.json shipped as a no-op once because
# the regenerate only happened at the bump step, after the tests.
echo "==> regenerating xcodeproj"
./scripts/generate.sh >/dev/null

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
IPHONE_SIM="${SIMULATOR_ID:-$(sim_named 'iPhone 17 Pro')}"; [[ -n "$IPHONE_SIM" ]] || IPHONE_SIM=$(sim_named 'iPhone')
IPAD_SIM="${IPAD_SIMULATOR_ID:-$(sim_named 'iPad Pro 11-inch')}"; [[ -n "$IPAD_SIM" ]] || IPAD_SIM=$(sim_named 'iPad')
MINI_SIM="${MINI_SIMULATOR_ID:-$(sim_named 'iPad mini')}"
if [[ "${SHIP_UNIT_ONLY:-0}" == "1" ]]; then
  echo "==> SHIP_UNIT_ONLY: unit tests only on iPhone (no XCUITest, no iPad)"
  SIMULATOR_ID="$IPHONE_SIM" ./scripts/run_tests.sh FindACribTests
else
  echo "==> running every test on iPhone ($IPHONE_SIM)"
  SIMULATOR_ID="$IPHONE_SIM" ./scripts/run_tests.sh
  [[ -n "$IPAD_SIM" ]] || { echo "error: no iPad simulator installed — the iPad gate cannot run" >&2; exit 1; }
  echo "==> running every test on iPad ($IPAD_SIM)"
  SIMULATOR_ID="$IPAD_SIM" ./scripts/run_tests.sh
  if [[ -n "$MINI_SIM" ]]; then
    echo "==> iPad tour on iPad mini ($MINI_SIM)"
    SIMULATOR_ID="$MINI_SIM" ./scripts/run_tests.sh FindACribUITests/IPadTourTests
  fi
fi

if [[ "${SHIP_SKIP_SMOKE:-0}" == "1" ]]; then echo "==> skipping smoke test"; else
  echo "==> smoke-testing a launch on iPhone"; SIMULATOR_ID="$IPHONE_SIM" ./scripts/smoke_test.sh
  echo "==> smoke-testing a launch on iPad"; SIMULATOR_ID="$IPAD_SIM" ./scripts/smoke_test.sh
fi

current=$(grep -m1 'CURRENT_PROJECT_VERSION:' "$PROJECT_YML" | sed -E 's/.*"([0-9]+)".*/\1/')
next=$((current + 1))
echo "==> bumping build $current -> $next"
sed -i '' "s/CURRENT_PROJECT_VERSION: \"$current\"/CURRENT_PROJECT_VERSION: \"$next\"/" "$PROJECT_YML"
./scripts/generate.sh >/dev/null

ASC_AUTH_FLAGS=(-authenticationKeyPath "$ASC_KEY_PATH" -authenticationKeyID "$ASC_KEY_ID" -authenticationKeyIssuerID "$ASC_ISSUER_ID")

echo "==> archiving"
rm -rf "$ARCHIVE" "$EXPORT_DIR"
# DEVELOPMENT_TEAM is in project.yml, but pass it anyway: automatic signing
# without a team fails with "requires a development team".
xcodebuild -project "$PROJECT" -scheme "$SCHEME" -configuration Release \
  -destination "generic/platform=iOS" -archivePath "$ARCHIVE" \
  -allowProvisioningUpdates "${ASC_AUTH_FLAGS[@]}" DEVELOPMENT_TEAM="$ASC_TEAM_ID" archive > build.nosync/archive.log 2>&1 \
  || { echo "error: archive failed" >&2; grep -E "error" build.nosync/archive.log | tail -20 >&2; exit 1; }
[[ -d "$ARCHIVE" ]] || { echo "error: archive missing" >&2; tail -30 build.nosync/archive.log >&2; exit 1; }

echo "==> exporting IPA"
xcodebuild -exportArchive -archivePath "$ARCHIVE" -exportPath "$EXPORT_DIR" \
  -exportOptionsPlist ExportOptions.plist -allowProvisioningUpdates "${ASC_AUTH_FLAGS[@]}" > build.nosync/export.log 2>&1 \
  || { echo "error: export failed" >&2; grep -iE "error" build.nosync/export.log | tail -20 >&2; exit 1; }
# The export names the IPA after CFBundleName ("Find A Crib.ipa"), not the
# product name — find it rather than guess it.
IPA=$(find "$EXPORT_DIR" -maxdepth 1 -name '*.ipa' | head -1)
[[ -n "$IPA" && -f "$IPA" ]] || { echo "error: IPA missing" >&2; tail -30 build.nosync/export.log >&2; exit 1; }

echo "==> uploading to TestFlight"
xcrun altool --upload-app -f "$IPA" -t ios --apiKey "$ASC_KEY_ID" --apiIssuer "$ASC_ISSUER_ID"
echo "==> shipped build $next"

echo "==> verifying internal tester auto-distribution"
"${PY:-$HOME/.venvs/spendcap/bin/python}" scripts/configure_internal_testers.py || echo "warning: configure_internal_testers.py reported a problem"

# ASC draws the app's header icon from the build attached to the App Store
# VERSION, not from the latest TestFlight upload; attach the newest processed
# build (never submits). Fresh uploads take minutes to process, so a
# "nothing to attach yet" here is normal right after a ship.
if [[ -f ASC_FREEZE ]]; then
  echo "==> App Store frozen (ios/ASC_FREEZE): TestFlight only, build not attached to any App Store version"
else
  echo "==> attaching newest processed build to the App Store version"
  "${PY:-$HOME/.venvs/spendcap/bin/python}" scripts/attach_build.py || echo "warning: attach_build.py reported a problem (re-run once the build has processed)"
fi
