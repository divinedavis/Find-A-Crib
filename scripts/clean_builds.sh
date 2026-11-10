#!/usr/bin/env bash
# Report or empty the per-worktree Xcode build trees (ios/build.nosync).
#
#   scripts/clean_builds.sh                    # dry run: show sizes, change nothing
#   scripts/clean_builds.sh --yes              # empty every idle tree
#   scripts/clean_builds.sh --yes --keep daily # leave the daily worktree's tree alone
#
# Why this exists: every worktree builds into its own ios/build.nosync. On
# 2026-11-10 nine checkouts held 19.4 GB there, 8.7 GB of it in the main
# checkout alone. The trees are build output — xcodebuild recreates them — so
# emptying them is the cheapest way to get disk back. Keep the worktree that
# holds the last archive/IPA if you want that build on disk; TestFlight already
# has the uploaded copy.
#
# What it will not do:
#   - touch source files: only the contents of ios/build.nosync directories;
#   - delete ship-history.jsonl, the one file in there that is a record rather
#     than output (ship_summary.py appends a line per ship and reads it back);
#   - empty a tree something wrote to in the last hour, or run at all while a
#     build or ship is in flight, unless --force.
set -euo pipefail
ROOT=${FAC_PROJECTS_DIR:-$HOME/projects}
BUSY_MINUTES=${FAC_BUILD_BUSY_MINUTES:-60}
PRESERVE=(ship-history.jsonl)
APPLY=0
FORCE=0
KEEP=()
usage() { sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; }
while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) APPLY=1 ;;
    --force) FORCE=1 ;;
    --keep) KEEP+=("${2:?--keep needs a worktree name}"); shift ;;
    --root) ROOT=${2:?--root needs a directory}; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

# Size of what would actually go: the tree minus the preserved files.
removable_kb() {
  local b=$1 kb keep_kb=0 p
  kb=$(du -sk "$b" | cut -f1)
  for p in "${PRESERVE[@]}"; do
    [ -f "$b/$p" ] && keep_kb=$((keep_kb + $(du -sk "$b/$p" | cut -f1)))
  done
  echo $((kb - keep_kb))
}
human_kb() { awk -v k="$1" 'BEGIN { if (k >= 1048576) printf "%.1f GB", k / 1048576; else printf "%.0f MB", k / 1024 }'; }

shopt -s nullglob
dirs=()
for d in "$ROOT"/dhcr-map*/; do
  b="${d}ios/build.nosync"
  [ -d "$b" ] || continue
  name=$(basename "${d%/}")
  keep=0
  # ${KEEP[@]+...}: macOS ships bash 3.2, where an empty array under `set -u`
  # is an unbound variable.
  for k in ${KEEP[@]+"${KEEP[@]}"}; do
    { [ "$name" = "$k" ] || [ "$name" = "dhcr-map-$k" ]; } && keep=1
  done
  if [ "$keep" -eq 1 ]; then
    printf "keep    %8s  %s\n" "$(du -sh "$b" | cut -f1)" "$b"
    continue
  fi
  if [ "$FORCE" -ne 1 ] && [ -n "$(find "$b" -maxdepth 2 -mmin "-$BUSY_MINUTES" -print -quit 2>/dev/null)" ]; then
    printf "busy    %8s  %s (written in the last %s min)\n" "$(du -sh "$b" | cut -f1)" "$b" "$BUSY_MINUTES"
    continue
  fi
  dirs+=("$b")
done
if [ "${#dirs[@]}" -eq 0 ]; then
  echo "No idle ios/build.nosync directories to clean under $ROOT."
  exit 0
fi
total_kb=0
for b in "${dirs[@]}"; do
  kb=$(removable_kb "$b")
  total_kb=$((total_kb + kb))
  printf "remove  %8s  %s\n" "$(human_kb "$kb")" "$b"
done
human=$(human_kb "$total_kb")
printf "\n%d tree(s), %s total\n" "${#dirs[@]}" "$human"
if [ "$APPLY" -ne 1 ]; then
  echo "Dry run. Re-run with --yes to remove them."
  exit 0
fi
# A ship spends minutes between xcodebuild calls (uploads, simulator boots), so
# looking for xcodebuild alone would let this run in the middle of one.
# Match the process itself, not any command line that mentions it: `pgrep -f
# xcodebuild` also hits a shell loop that is only waiting for builds to finish
# (`while pgrep -f xcodebuild ...`), and on 2026-11-10 one such loop held this
# script off for three hours with no build running.
build_running() {
  pgrep -x xcodebuild >/dev/null 2>&1 && return 0
  # A script run as `bash ship.sh`, `./ship.sh` or `/bin/bash /path/ship.sh`:
  # argv[0] is the shell or the script, never something that merely quotes it.
  pgrep -f '^(/bin/|/usr/bin/env )?(ba|z)?sh [^ ]*(ship|daily_ship|test_affected)\.sh( |$)|^[^ ]*/(ship|daily_ship|test_affected)\.sh( |$)' >/dev/null 2>&1
}
if [ "$FORCE" -ne 1 ] && build_running; then
  echo "error: a build or ship is running; wait for it or pass --force" >&2
  exit 1
fi
for b in "${dirs[@]}"; do
  args=()
  for p in "${PRESERVE[@]}"; do args+=(! -name "$p"); done
  find "$b" -mindepth 1 -maxdepth 1 "${args[@]}" -exec rm -rf -- {} +
  echo "emptied $b"
done
echo "Freed approximately $human."
