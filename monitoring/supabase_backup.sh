#!/usr/bin/env bash
# Weekly pg_dump of every Supabase project listed in /etc/supabase-backup/,
# run on the divinedavis.com droplet (159.203.110.79) so the copy lives on a
# different machine from both Supabase and the app droplets.
#
# Why: free-plan Supabase projects get NO backups — Supabase's own docs say
# to `db dump` them yourself and keep the copies off-site (checked
# 2026-10-01). One env file per project (0600):
#   /etc/supabase-backup/<name>.env   PGHOST= PGUSER= PGPASSWORD= (session pooler, port 5432)
#                                     optional MIN_BYTES= (default 1000000) for small DBs
# Dumps: /var/backups/supabase/<name>/<name>-YYYY-MM-DD.dump (custom format,
# restore with pg_restore), 8 weeks kept.
#
# WEEKLY, not nightly, on purpose (owner: no backups that cost money). Cost
# is $0 either way — a free-org project is never billed — but each dump
# pulls ~130 MB through the pooler, which Supabase counts as egress against
# the free plan's 5 GB/month; nightly was ~3.9 GB, and a free project over
# quota gets restricted. Weekly is ~0.6 GB. Measured 2026-10-01. A failed or suspiciously small dump
# emails the owner through uptime-watch's SMTP settings.
set -uo pipefail
PG_DUMP=/usr/lib/postgresql/17/bin/pg_dump
OUT=/var/backups/supabase
KEEP_DAYS=60
fail=()
for envf in /etc/supabase-backup/*.env; do
  name=$(basename "$envf" .env)
  dir="$OUT/$name"; mkdir -p "$dir"; chmod 700 "$OUT" "$dir"
  file="$dir/$name-$(date -u +%F).dump"
  if ( set -a; . "$envf"; set +a; export PGPORT=${PGPORT:-5432} PGDATABASE=${PGDATABASE:-postgres} PGSSLMODE=require
       "$PG_DUMP" -Fc --no-owner --no-privileges -f "$file.tmp" ) 2>"$dir/last-error.log"; then
    size=$(stat -c %s "$file.tmp")
    # A truncated dump is the failure this catches; a small app (Crease ~0.5 MB)
    # sets its own floor in its env file.
    min=$(sed -n 's/^MIN_BYTES=\([0-9]*\)$/\1/p' "$envf"); min=${min:-1000000}
    if [ "$size" -lt "$min" ]; then
      fail+=("$name: dump is only $size bytes"); mv "$file.tmp" "$file.small"
    else
      mv "$file.tmp" "$file"; chmod 600 "$file"
      echo "$(date -u +%FT%TZ) $name ok $size bytes"
    fi
  else
    fail+=("$name: pg_dump failed — $(tail -c 300 "$dir/last-error.log")"); rm -f "$file.tmp"
  fi
  find "$dir" -name "$name-*.dump*" -mtime +$KEEP_DAYS -delete
done
if [ ${#fail[@]} -gt 0 ]; then
  printf '%s\n' "${fail[@]}" >&2
  python3 - "${fail[@]}" <<'PY'
import sys, importlib.machinery, importlib.util
loader = importlib.machinery.SourceFileLoader("uw", "/usr/local/bin/uptime-watch")
spec = importlib.util.spec_from_loader("uw", loader); uw = importlib.util.module_from_spec(spec); loader.exec_module(uw)
uw.send(uw.env(), "Supabase backup FAILED", "Nightly dump on divinedavis.com droplet:\n\n" + "\n".join(sys.argv[1:]))
PY
  exit 1
fi
