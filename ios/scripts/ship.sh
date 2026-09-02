#!/usr/bin/env bash
# Find A Crib — test, smoke-launch, bump build, archive, export, upload to
# TestFlight. Build number lives in project.yml (CURRENT_PROJECT_VERSION)
# because the pbxproj is generated. SHIP_RUN_UI=1 also gates on UI tests.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f scripts/asc-config.env ]] || { echo "error: scripts/asc-config.env missing (copy .example)" >&2; exit 1; }
# shellcheck disable=SC1091
source scripts/asc-config.env

PROJECT="FindACrib.xcodeproj"; SCHEME="FindACrib"; PROJECT_YML="project.yml"
ARCHIVE="build.nosync/FindACrib.xcarchive"; EXPORT_DIR="build.nosync/export"; IPA="$EXPORT_DIR/FindACrib.ipa"

echo "==> refreshing seed data"
./scripts/refresh_data.sh >/dev/null

echo "==> running tests"
if [[ "${SHIP_RUN_UI:-0}" == "1" ]]; then ./scripts/run_tests.sh; else ./scripts/run_tests.sh FindACribTests; fi

if [[ "${SHIP_SKIP_SMOKE:-0}" == "1" ]]; then echo "==> skipping smoke test"; else
  echo "==> smoke-testing a simulator launch"; ./scripts/smoke_test.sh; fi

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
echo "==> attaching newest processed build to the App Store version"
"${PY:-$HOME/.venvs/spendcap/bin/python}" scripts/attach_build.py || echo "warning: attach_build.py reported a problem (re-run once the build has processed)"
