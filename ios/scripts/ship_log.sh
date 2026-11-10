# Sourced by ship.sh: stage timestamps and memory samples in one events file,
# summed up in one "SHIP SUMMARY" line when the ship ends, pass or fail
# (scripts/ship_summary.py). Same kit as Marracat's (owner, 2026-11-09:
# "do these recommendations apply to our other apps? if so, implement them").
#
#   ship_log_start        start the events file and the watcher
#   stage "<name>"        prints "==> HH:MM:SS name" and records it
#   note key=value        build=42, tier=fast
#   ship_done             the ship reached its end: the summary says "ok"
#
# No trap is needed (three of the ship scripts have their own): a watcher
# samples memory every 5 s while the ship's process lives, then prints the
# summary itself. A ship that never called ship_done is reported FAILED.
# Memory "used" is Activity Monitor's: app memory + wired + compressed.
SHIP_LOG_DIR="${SHIP_LOG_DIR:-build}"
SHIP_EVENTS="$SHIP_LOG_DIR/ship-events.tsv"
SHIP_HISTORY="$SHIP_LOG_DIR/ship-history.jsonl"
SHIP_LOG_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ship_event() { printf '%s\t%s\t%s\n' "$(date +%s)" "$1" "$2" >> "$SHIP_EVENTS" 2>/dev/null || true; }
stage() { echo "==> $(date +%T) $1"; ship_event stage "$1"; }
note() { ship_event note "$1"; }
ship_done() { ship_event note "result=ok"; }

ship_used_gb() {
    vm_stat | awk -v ps="$(sysctl -n hw.pagesize)" '
        /^Anonymous pages/        { gsub(/\./, "", $3); a = $3 }
        /^Pages purgeable/        { gsub(/\./, "", $3); p = $3 }
        /^Pages wired down/       { gsub(/\./, "", $4); w = $4 }
        /occupied by compressor/  { gsub(/\./, "", $5); c = $5 }
        END { printf "%.1f", (a - p + w + c) * ps / 1073741824 }'
}

ship_log_start() {
    mkdir -p "$SHIP_LOG_DIR"
    : > "$SHIP_EVENTS"
    local ship=$$
    (
        set +e
        tick=0
        while kill -0 "$ship" 2>/dev/null; do
            if (( tick % 5 == 0 )); then
                swap=$(sysctl -n vm.swapusage 2>/dev/null | sed -E 's/.*used = ([0-9.]+)M.*/\1/')
                printf '%s\tmem\t%s\t%s\n' "$(date +%s)" "$(ship_used_gb 2>/dev/null || echo 0)" "${swap:-0}" >> "$SHIP_EVENTS"
            fi
            tick=$((tick + 1)); sleep 1
        done
        rc=1; grep -q "$(printf '\tnote\tresult=ok')" "$SHIP_EVENTS" 2>/dev/null && rc=0
        python3 "$SHIP_LOG_HOME/ship_summary.py" "$SHIP_EVENTS" --result "$rc" --history "$SHIP_HISTORY" || true
    ) &
    stage "start"
}
