#!/usr/bin/env bash
# Install (or refresh) the weekly In-App Events job: asc_events_auto.py --apply
# every Monday 09:50 on this Mac (launchd runs a missed one at the next wake).
# The scripts are copied out of the repo so a checkout mid-edit never runs;
# re-run this after changing them. Log: ~/Library/Logs/fac-events.log
set -euo pipefail
cd "$(dirname "$0")"
DEST="$HOME/Library/Application Support/fac-events"
PLIST="$HOME/Library/LaunchAgents/com.divinedavis.findacrib-events.plist"
PY="${PY:-$HOME/.venvs/spendcap/bin/python}"
mkdir -p "$DEST"
cp asc_events_auto.py asc_app_events.py asc_creative_assets.py "$DEST/"
cp ../FindACrib/Resources/holidays.json "$DEST/"   # every holiday gets an event (10/24)
cp asc-config.env "$DEST/" && chmod 600 "$DEST/asc-config.env"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.divinedavis.findacrib-events</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$DEST/asc_events_auto.py</string>
    <string>--apply</string>
  </array>
  <key>WorkingDirectory</key><string>$DEST</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key><integer>1</integer>
    <key>Hour</key><integer>9</integer>
    <key>Minute</key><integer>50</integer>
  </dict>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/fac-events.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/fac-events.log</string>
</dict>
</plist>
EOF
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed: $PLIST (Mondays 09:50); log ~/Library/Logs/fac-events.log"
