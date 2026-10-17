#!/usr/bin/env bash
# Raw screens for the App Store panels: signs a 6.9" simulator in with the App
# Review demo account (scripts/asc-config.env) and runs MarketingCapture, which
# writes marketing/raw/<screen>.png. Then: python3 scripts/make_screenshots.py
# --ipad: the iPad 13" screens into marketing/raw-ipad (make_screenshots.py --ipad).
# ONLY=agent,detail recaptures just those screens.
set -euo pipefail
cd "$(dirname "$0")/.."
DEVICE="iPhone 17 Pro Max"; RAW=marketing/raw
if [[ "${1:-}" == "--ipad" ]]; then DEVICE="iPad Pro 13-inch (M5)"; RAW=marketing/raw-ipad; fi
SIM="${SIMULATOR_ID:-$(xcrun simctl list devices available -j | python3 -c "import json,sys;d=json.load(sys.stdin);print(next(v['udid'] for r in d['devices'].values() for v in r if v['name']==sys.argv[1]))" "$DEVICE")}"
set -a; source scripts/asc-config.env; set +a
xcrun simctl boot "$SIM" 2>/dev/null || true
xcrun simctl bootstatus "$SIM" -b >/dev/null
xcrun simctl status_bar "$SIM" override --time 9:41 --batteryState charged --batteryLevel 100 \
  --wifiBars 3 --cellularMode active --cellularBars 4 --operatorName ""
mkdir -p "$RAW"
TEST_RUNNER_MARKETING_RAW="$PWD/$RAW" TEST_RUNNER_MARKETING_ONLY="${ONLY:-}" TEST_RUNNER_DEMO_EMAIL="$ASC_DEMO_EMAIL" \
TEST_RUNNER_DEMO_PASSWORD="$ASC_DEMO_PASSWORD" \
xcodebuild test -project FindACrib.xcodeproj -scheme FindACrib -destination "platform=iOS Simulator,id=$SIM" \
  -derivedDataPath build.nosync/marketing -only-testing:FindACribUITests/MarketingCapture -quiet
xcrun simctl status_bar "$SIM" clear
