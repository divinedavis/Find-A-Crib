#!/usr/bin/env bash
# Waits until the Mac and the simulator have settled, so the performance gate
# measures the app and not whatever else is running.
#
# Two causes of false perf failures, both seen in October 2026:
#   * Another session's xcodebuild on the same Mac: 2026-10-21 build 153 failed
#     launch at 2.05 s against a 0.91 s baseline with the load average at ~90.
#   * A freshly erased or first-booted simulator runs mediaanalysisd at ~180%
#     CPU for minutes (Marracat 2026-10-18: 2.7-4.9 s vs 1.47 s).
# Quiet = the 1-minute load average under QUIET_LOAD and every simulator
# process together under QUIET_PCT, for QUIET_FOR seconds in a row. Gives up
# after max_seconds and measures anyway (the gate then re-measures once).
#
#   SIM_UDID=<udid> ./scripts/wait_sim_quiet.sh [max_seconds]
set -euo pipefail
: "${SIM_UDID:?SIM_UDID is required}"
MAX="${1:-900}"
QUIET_PCT=25
QUIET_LOAD="${QUIET_LOAD:-$(( $(sysctl -n hw.ncpu) * 6 / 10 ))}"   # 6 on this 10-core Mac
QUIET_FOR=30

xcrun simctl boot "$SIM_UDID" 2>/dev/null || true
start=$(date +%s); calm=0
while :; do
    # Simulator processes run from the runtime's RuntimeRoot; ps prints that path.
    pct=$(ps -axo %cpu=,command= | awk '/RuntimeRoot/ && !/awk/ {s += $1} END {printf "%d", s}')
    load=$(sysctl -n vm.loadavg | awk '{printf "%d", $2}')
    if (( pct < QUIET_PCT && load < QUIET_LOAD )); then calm=$((calm + 5)); else calm=0; fi
    (( calm >= QUIET_FOR )) && { echo "quiet (load $load, simulator ${pct}% CPU) after $(( $(date +%s) - start )) s"; exit 0; }
    if (( $(date +%s) - start >= MAX )); then
        echo "warning: still busy after ${MAX} s (load $load, simulator ${pct}% CPU); measuring anyway" >&2
        exit 0
    fi
    sleep 5
done
