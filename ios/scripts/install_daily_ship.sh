#!/usr/bin/env bash
# Installs launchd com.findacrib.daily-ship: ios/scripts/daily_ship.sh at
# 03:05 from ~/projects/dhcr-map-daily, a worktree used only by this job.
# (Marracat's starts at 03:00; whichever runs second waits for the first.)
# Creates the worktree if missing; the two gitignored inputs link to the main
# checkout's copies.
set -euo pipefail
main="$HOME/projects/dhcr-map"
daily="$HOME/projects/dhcr-map-daily"
if [[ ! -d "$daily" ]]; then
    git -C "$main" fetch -q origin
    git -C "$main" worktree add --detach "$daily" origin/main
fi
for f in ios/Secrets.xcconfig ios/scripts/asc-config.env; do
    [[ -e "$daily/$f" ]] || ln -s "$main/$f" "$daily/$f"
done
label=com.findacrib.daily-ship
plist="$HOME/Library/LaunchAgents/$label.plist"
cat >"$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string><string>-c</string>
    <string>mkdir -p $daily/ios/build.nosync; $daily/ios/scripts/daily_ship.sh &gt;&gt; $daily/ios/build.nosync/daily-ship.log 2&gt;&amp;1</string>
  </array>
  <key>WorkingDirectory</key><string>$daily/ios</string>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>5</integer></dict>
</dict>
</plist>
EOF
launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist"
echo "installed $label: daily at 03:05 -> $daily/ios/build.nosync/daily-ship.log"
