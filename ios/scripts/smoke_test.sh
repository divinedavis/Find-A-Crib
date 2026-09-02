#!/usr/bin/env bash
# Build, install and cold-launch in a simulator to prove the app starts.
# Memory rule: smoke-test a launch before every TestFlight ship.
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="FindACrib.xcodeproj"; SCHEME="FindACrib"; BUNDLE_ID="com.divinedavis.findacrib"
DERIVED_DATA="build.nosync/smoke"

SIMULATOR_ID="${SIMULATOR_ID:-}"
if [[ -z "$SIMULATOR_ID" ]]; then
  SIMULATOR_ID=$(xcrun simctl list devices booted -j 2>/dev/null | python3 -c "import json,sys;d=json.load(sys.stdin);print(next(iter([dev['udid'] for r in d['devices'].values() for dev in r if dev.get('state')=='Booted']), ''))" 2>/dev/null || echo "")
fi
if [[ -z "$SIMULATOR_ID" ]]; then
  SIMULATOR_ID=$(xcrun simctl list devices available -j | python3 -c "import json,sys;d=json.load(sys.stdin);print(next(iter([dev['udid'] for r in d['devices'].values() for dev in r if 'iPhone' in dev.get('name','') and dev.get('isAvailable')]), ''))")
fi
[[ -n "$SIMULATOR_ID" ]] || { echo "error: no iPhone simulator" >&2; exit 1; }
echo "==> simulator $SIMULATOR_ID"
xcrun simctl boot "$SIMULATOR_ID" 2>/dev/null || true
xcrun simctl bootstatus "$SIMULATOR_ID" -b >/dev/null 2>&1 || true

# ENABLE_DEBUG_DYLIB=NO: Xcode 26's debug-dylib layout launches from Xcode but
# `simctl launch` rejects it ("denied by service delegate") — not a crash.
echo "==> building"
xcodebuild -project "$PROJECT" -scheme "$SCHEME" -configuration Debug \
  -destination "platform=iOS Simulator,id=$SIMULATOR_ID" -derivedDataPath "$DERIVED_DATA" \
  ENABLE_DEBUG_DYLIB=NO CODE_SIGNING_ALLOWED=NO build >/dev/null

APP=$(find "$DERIVED_DATA/Build/Products" -maxdepth 3 -name 'FindACrib.app' | head -1)
[[ -n "$APP" ]] || { echo "error: FindACrib.app not found" >&2; exit 1; }
echo "==> installing"
xcrun simctl uninstall "$SIMULATOR_ID" "$BUNDLE_ID" 2>/dev/null || true
xcrun simctl install "$SIMULATOR_ID" "$APP"
echo "==> launching"
PID=$(xcrun simctl launch "$SIMULATOR_ID" "$BUNDLE_ID" | sed -E 's/.*: ([0-9]+)$/\1/')
[[ -n "$PID" ]] || { echo "error: launch did not report a pid" >&2; exit 1; }

crash_seen() { [[ -n "$(find ~/Library/Logs/DiagnosticReports -name 'FindACrib*' -newermt '-2 minutes' 2>/dev/null)" ]]; }
# Straight after a UI-test run the simulator is still settling: the first
# launch can be torn down by SpringBoard with no crash report at all, and a
# gate that fails on that gets ignored. Poll longer, and if nothing is
# running and nothing crashed, launch once more before calling it.
alive=0
for attempt in 1 2; do
  for _ in $(seq 1 15); do
    if xcrun simctl spawn "$SIMULATOR_ID" launchctl list 2>/dev/null | grep -q "$BUNDLE_ID"; then alive=1; break 2; fi
    if crash_seen; then break 2; fi
    sleep 2
  done
  [[ $attempt -eq 1 ]] && { echo "==> not running yet and no crash report; relaunching once"; xcrun simctl launch "$SIMULATOR_ID" "$BUNDLE_ID" >/dev/null || true; }
done
if [[ "$alive" -ne 1 ]]; then
  echo "error: $BUNDLE_ID not running after launch" >&2
  crash_seen && find ~/Library/Logs/DiagnosticReports -name 'FindACrib*' -newermt '-2 minutes' | head -3 >&2
  exit 1
fi
echo "==> smoke test passed (pid $PID)"
