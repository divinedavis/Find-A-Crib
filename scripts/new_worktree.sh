#!/usr/bin/env bash
# Create a sibling worktree and give it the gitignored data a fresh checkout
# lacks.
#
#   scripts/new_worktree.sh rr-filters            # branch + ../dhcr-map-rr-filters
#   scripts/new_worktree.sh rr-filters origin/main
#   scripts/new_worktree.sh hotfix --no-fetch     # use the local origin/main ref
#   scripts/new_worktree.sh hotfix --no-refresh   # clone the data as it is, offline
#
# Why: a new worktree gets only tracked files. The web app boots from
# buildings.slim.json, the iOS app needs its seed JSON, and the builders need
# buildings_geo.json / buildings_hpd.json / the city extracts — all gitignored,
# all present only in the main checkout. Copying them by hand is the step
# everyone forgets, and the failure mode is a silent fallback (index.html
# fetches buildings.min.json instead of slim) or a 404 in the app.
#
# On APFS, `cp -c` clones: the copy is instant and costs no extra disk until
# one side is modified. On another filesystem it falls back to a normal copy.
#
# The main checkout's copies are only as fresh as the last time someone
# rebuilt them by hand: on 2026-11-10 its NYC buildings.slim.json was from
# August. So before cloning, every file the live site serves publicly is
# re-downloaded from findacrib.com into the main checkout if the copy there is
# missing or older than FAC_DATA_MAX_AGE_DAYS (default 7). --no-refresh skips
# that. Files that never leave the pipeline (buildings_geo.json and friends)
# cannot be refreshed this way and are cloned as they are.
#
# The worktree is based on origin/main, which is fetched first unless
# --no-fetch is given.
set -euo pipefail
NAME=""
BASE=""
NO_FETCH=0
NO_DATA=0
NO_REFRESH=0
SITE=${FAC_SITE:-https://findacrib.com}
MAX_AGE=${FAC_DATA_MAX_AGE_DAYS:-7}
while [ $# -gt 0 ]; do
  case "$1" in
    --no-fetch) NO_FETCH=1 ;;
    --no-data) NO_DATA=1 ;;
    --no-refresh) NO_REFRESH=1 ;;
    -h|--help) sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *)
      if [ -z "$NAME" ]; then
        NAME=$1
      elif [ -z "$BASE" ]; then
        BASE=$1
      else
        echo "unexpected argument: $1" >&2
        exit 2
      fi
      ;;
  esac
  shift
done
BASE=${BASE:-origin/main}
if [ -z "$NAME" ]; then
  echo "usage: scripts/new_worktree.sh <branch> [base] [--no-fetch] [--no-data] [--no-refresh]" >&2
  exit 2
fi
COMMON=$(git rev-parse --path-format=absolute --git-common-dir)
MAIN=$(dirname "$COMMON")
WT="${FAC_WORKTREE_ROOT:-$MAIN-$NAME}"
if [ -e "$WT" ]; then
  echo "error: $WT already exists" >&2
  exit 1
fi
if [ "$NO_FETCH" -eq 0 ]; then
  echo "==> fetching origin"
  git -C "$MAIN" fetch origin --prune
fi
echo "==> creating $WT from $BASE"
if git -C "$MAIN" show-ref --verify --quiet "refs/heads/$NAME"; then
  git -C "$MAIN" worktree add "$WT" "$NAME"
else
  git -C "$MAIN" worktree add -b "$NAME" "$WT" "$BASE"
fi
if [ "$NO_DATA" -eq 1 ]; then
  echo "==> skipping data (--no-data)"
  exit 0
fi
# Public files: "path in the checkout|path on the site". Only files anyone can
# already download; config.js is deliberately absent (the local one carries
# localhost-only keys the live one does not).
PUBLIC=(
  "buildings.slim.json|buildings.slim.json"
  "buildings.hpd.json|buildings.hpd.json"
  "featured.json|featured.json"
  "web/sf/buildings.slim.json|sf/buildings.slim.json"
  "web/sf/buildings.hpd.json|sf/buildings.hpd.json"
  "web/la/buildings.slim.json|la/buildings.slim.json"
  "web/la/buildings.hpd.json|la/buildings.hpd.json"
  "web/dc/buildings.slim.json|dc/buildings.slim.json"
  "web/dc/buildings.hpd.json|dc/buildings.hpd.json"
  "ios/FindACrib/Resources/Data/buildings.slim.json.gz|buildings.slim.json.gz"
)
# A download replaces the main checkout's copy only if it looks like what it
# claims to be; an error page saved as buildings.slim.json would boot the app
# into an empty map.
looks_right() {  # <downloaded file> <name it will be saved under>
  case "$2" in
    # From stdin: gzip -t refuses a file whose name does not end in .gz.
    *.gz) gzip -t <"$1" 2>/dev/null ;;
    *) case "$(head -c 1 "$1")" in "{"|"[") return 0 ;; *) return 1 ;; esac ;;
  esac
}
if [ "$NO_REFRESH" -eq 0 ]; then
  refreshed=0
  for pair in "${PUBLIC[@]}"; do
    rel=${pair%%|*}
    dst="$MAIN/$rel"
    if [ -f "$dst" ] && [ -z "$(find "$dst" -mtime "+$MAX_AGE" -print)" ]; then
      continue
    fi
    [ -d "$(dirname "$dst")" ] || continue
    tmp="$dst.download.$$"
    # No -R: the file's date then means "checked against live on this day",
    # which is what the age test above needs. The city files change rarely, and
    # keeping the server's date would re-download them on every run.
    if curl -fsS --max-time 180 -o "$tmp" "$SITE/${pair##*|}" && looks_right "$tmp" "$rel"; then
      mv "$tmp" "$dst"
      refreshed=$((refreshed + 1))
    else
      rm -f "$tmp"
      echo "warning: could not refresh $rel from $SITE; cloning the copy on disk" >&2
    fi
  done
  echo "==> refreshed $refreshed public data file(s) in $MAIN from $SITE"
fi
# Runtime files first: without these the app still loads, but it loads the
# wrong thing (buildings.min.json instead of slim) or loses Plus/featured data.
DATA=(
  buildings.slim.json
  buildings.slim.json.gz
  buildings.hpd.json.gz
  buildings.min.json.gz
  buildings.json
  buildings_geo.json
  buildings_geo_nta.json
  buildings_hpd.json
  buildings.hpd.json
  web/config.js
  featured.json
  seo_lastmod.json
  vacancies.json
  listings_zumper.json
  listings_apify.json
  apify_export.json
  agent_phones.json
  hpd_contacts.json
  web/sf/buildings.slim.json
  web/sf/buildings.hpd.json
  web/sf/buildings.min.json.gz
  web/la/buildings.slim.json
  web/la/buildings.hpd.json
  web/la/buildings.min.json.gz
  web/dc/buildings.slim.json
  web/dc/buildings.hpd.json
  web/dc/buildings.min.json.gz
  web/westchester/buildings.slim.json
  ios/FindACrib/Resources/Data/buildings.slim.json.gz
  ios/Secrets.xcconfig
  ios/scripts/asc-config.env
  ios/scripts/appstore.json
  growth/state.json
  growth/.anthropic_key
)
bytes=0
copied=0
stale=()
for rel in "${DATA[@]}"; do
  src="$MAIN/$rel"
  dst="$WT/$rel"
  [ -f "$src" ] || continue
  # Never overwrite a tracked file: the worktree already has the right one.
  if git -C "$WT" ls-files --error-unmatch "$rel" >/dev/null 2>&1; then
    continue
  fi
  # Only gitignored files. Anything else would show up as untracked in a
  # worktree that should start clean, one `git add -A` away from a commit.
  git -C "$WT" check-ignore -q "$rel" || continue
  mkdir -p "$(dirname "$dst")"
  if ! cp -c "$src" "$dst" 2>/dev/null; then
    cp -p "$src" "$dst"
  fi
  case "$rel" in
    *.json|*.gz) [ -n "$(find "$src" -mtime +30 -print)" ] && stale+=("$rel") ;;
  esac
  bytes=$((bytes + $(wc -c <"$src")))
  copied=$((copied + 1))
done
printf "==> cloned %d data file(s), %.0f MB (APFS clones share blocks until written)\n" \
  "$copied" "$(awk -v b="$bytes" 'BEGIN { print b / 1024 / 1024 }')"
if [ "${#stale[@]}" -gt 0 ]; then
  echo "note: ${#stale[@]} cloned file(s) are over 30 days old in $MAIN:"
  printf '        %s\n' "${stale[@]}"
fi
echo
echo "Next:"
echo "  cd $WT"
echo "  ios/scripts/generate.sh      # regenerate the Xcode project"
echo "  python3 scripts/preview.py   # the site with your web/ files over live data"
