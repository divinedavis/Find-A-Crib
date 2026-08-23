#!/usr/bin/env bash
# Weekly HPD refresh: re-pull violation + complaint counts and republish the blob
# the map loads. Installed as /etc/cron.d/rentmap-hpd.
#
# HPD is the most volatile dataset on the site and was the only major one with no
# schedule. On 2026-08-23 the live counts were still the 2026-06-28 pull, run with
# logic corrected on 08-18 but never re-executed: 3,206,291 open violations served
# against a true 1,104,222, wrong on 45,678 of 47,165 buildings, with nothing
# anywhere reporting a problem.
#
#   ./scripts/refresh_hpd.sh              # pull, refresh, republish
#   ./scripts/refresh_hpd.sh --dry-run    # fetch and report, write nothing
#
# The whole body is a function called on the last line. Bash reads a script
# incrementally, so a `git pull` that rewrites this file mid-run would otherwise
# resume at a byte offset into different text; parsing a function up front means
# the version that started the run is the version that finishes it.
set -euo pipefail

REPO=/root/Find-A-Crib
DOCROOT=/var/www/rent-map

main() {
  cd "$REPO"
  git pull -q --ff-only || echo "  ! git pull failed; running the checked-out version"

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] HPD refresh starting"
  python3 refresh_hpd_counts.py --docroot "$DOCROOT" "$@"

  # The dashboard API caches the blob in memory, so it serves the old counts
  # until it is restarted. Non-fatal: a stale API is worse than a failed refresh,
  # but neither should abort a run that already published correct data.
  if [ "${1:-}" != "--dry-run" ]; then
    systemctl restart findacrib-api 2>/dev/null || echo "  ! findacrib-api restart failed"
  fi

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] HPD refresh complete"
}

main "$@"
