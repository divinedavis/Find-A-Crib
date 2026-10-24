# One build at a time on this Mac, for every app and session (owner,
# 2026-10-23: "two builds are NOT allowed to run at the same time").
# Sourced by ship.sh, daily_ship.sh and run_tests.sh.
#
# Until now "is something building?" was guessed from process names, and the
# guesses went wrong twice in one week: both nightly builds ran at once, and
# a scheduled run shipped a duplicate build. A lock directory is exact: mkdir
# either creates it or fails, atomically. The holder's PID and a label sit in
# $BUILD_LOCK_DIR/owner; a lock whose PID is gone is stale and is cleared.
#
#   build_lock_take "<label>"   wait until the lock is ours (prints who holds it)
#   build_lock_try  "<label>"   one attempt; 0 = ours, 1 = someone else's
#
# Re-entrant: BUILD_LOCK_HELD=1 (exported by the holder) means a parent
# script already holds it, so ship.sh under daily_ship.sh and run_tests.sh
# under ship.sh don't wait on themselves. Released when the holder exits.
# The path is shared on purpose: another app's scripts can take the same lock.
BUILD_LOCK_DIR="${BUILD_LOCK_DIR:-$HOME/Library/Caches/build-lock}"

build_lock_holder() { cat "$BUILD_LOCK_DIR/owner" 2>/dev/null || echo "unknown"; }

build_lock_try() {
  [[ "${BUILD_LOCK_HELD:-0}" == "1" ]] && return 0
  if ! mkdir "$BUILD_LOCK_DIR" 2>/dev/null; then
    local pid age
    pid=$(awk '{print $1}' "$BUILD_LOCK_DIR/owner" 2>/dev/null || true)
    age=$(( $(date +%s) - $(stat -f %m "$BUILD_LOCK_DIR" 2>/dev/null || date +%s) ))
    # Stale: its holder is gone, or it never got an owner line (killed
    # between mkdir and the write) and is more than a minute old.
    if { [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; } || { [[ -z "$pid" ]] && (( age > 60 )); }; then
      rm -rf "$BUILD_LOCK_DIR"
      mkdir "$BUILD_LOCK_DIR" 2>/dev/null || return 1
    else
      return 1
    fi
  fi
  echo "$$ $1 $(date '+%F %T')" > "$BUILD_LOCK_DIR/owner"
  export BUILD_LOCK_HELD=1
  trap build_lock_release EXIT
  return 0
}

build_lock_take() {
  local said=0
  until build_lock_try "$1"; do
    (( said )) || { echo "==> $(date +%T) waiting for the build lock (held by: $(build_lock_holder))"; said=1; }
    sleep 15
  done
}

build_lock_release() {
  [[ "$(awk '{print $1}' "$BUILD_LOCK_DIR/owner" 2>/dev/null)" == "$$" ]] && rm -rf "$BUILD_LOCK_DIR"
  return 0
}
