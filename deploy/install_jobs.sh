#!/bin/bash
# Install / re-apply the Find A Crib cron-job sandbox on the droplet.
#
#   scripts/deploy_jobs.sh            # from the Mac: copies deploy/ and runs this
#
# Until 2026-10-07 all 18 /etc/cron.d/rentmap-* jobs ran as root. They parse
# third-party PDFs (flyer_reader.py / pypdf), drive headless Chrome against
# agents' sites, and read scraped JSON/HTML — and every one of them had the
# API's .env (service-role, Stripe, Anthropic, SMTP), the APNs key and the
# GitHub push key within reach. After this script:
#
#   * jobs run as `scraper` (error_report.py as `facops`, which alone gets the
#     adm/systemd-journal groups it needs to read nginx logs and journalctl);
#   * each cron line names the env sets it gets (`fac-run supabase,smtp -- …`),
#     written from ONE root-only source file into /etc/findacrib/env/*.env;
#   * code, venv and browser cache live outside the web docroot
#     (/opt/findacrib/{venv,ms-playwright}); the docroot holds only site files;
#   * the only root steps left are this installer, deploy_*.sh, and the GeoIP
#     download (a root-owned copy in /usr/local/sbin — root never executes
#     code from the scraper-writable checkout).
#
# Idempotent: every step checks before it changes anything, so re-running it
# after a deploy just re-asserts ownership and re-installs the cron files.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)          # the copied deploy/ directory
REPO=/root/Find-A-Crib
DOC=/var/www/rent-map
BUILD=/root/dhcr-build
API=/root/findacrib-api
OPT=/opt/findacrib
ETC=/etc/findacrib
ENVDIR=$ETC/env
SECRETS=$ETC/secrets
SOURCE=$ETC/source.env
say() { printf '==> %s\n' "$*"; }

# ---------------------------------------------------------------- users
say "users"
id scraper >/dev/null 2>&1 || useradd --system --home-dir /var/lib/scraper --create-home --shell /usr/sbin/nologin scraper
id facops  >/dev/null 2>&1 || useradd --system --home-dir /var/lib/facops  --create-home --shell /usr/sbin/nologin facops
usermod -aG adm,systemd-journal facops
# Both need to traverse /root to reach the checkout (no read, no listing).
setfacl -m u:scraper:x,u:facops:x /root
# error_report.py reads appstore.json (scp'd there by the Mac's launchd job).
setfacl -m u:facops:x $API

# ---------------------------------------------------------------- secrets
say "secrets"
install -d -o root -g root -m 0755 $ETC
install -d -o root -g root -m 0751 $ENVDIR
install -d -o root -g root -m 0751 $SECRETS
if [ ! -f "$SOURCE" ]; then
  # One-time migration: growth.env (+ the Anthropic key from the API .env,
  # which only flyer_reader.py needs) becomes the single source of truth.
  [ -f $REPO/growth.env ] || { echo "no $SOURCE and no $REPO/growth.env to migrate" >&2; exit 1; }
  umask 077
  { cat $REPO/growth.env; echo; grep -E '^(ANTHROPIC_API_KEY|AI_MONTHLY_CAP_MICROS)=' $API/.env || true; } > "$SOURCE"
  umask 022
fi
chown root:root "$SOURCE"; chmod 0600 "$SOURCE"
# Key files move out of the checkout (which the job user can write).
for f in $REPO/secrets/AuthKey_*.p8; do
  [ -f "$f" ] && mv -f "$f" $SECRETS/
done
[ -f $REPO/growth/.gsc_key.json ] && mv -f $REPO/growth/.gsc_key.json $SECRETS/gsc_key.json
for f in $SECRETS/*; do [ -f "$f" ] && { setfacl -b "$f"; chown root:scraper "$f"; chmod 0440 "$f"; }; done
P8=$(ls $SECRETS/AuthKey_*.p8 2>/dev/null | head -n 1 || true)

# mkenv <name> <group> KEY... — write $ENVDIR/<name>.env with just those keys.
mkenv() {
  local name=$1 group=$2; shift 2
  local tmp; tmp=$(mktemp)
  ( set -a; . "$SOURCE"; set +a
    # Overrides for paths that moved out of the checkout.
    [ -n "$P8" ] && APNS_KEY_PATH=$P8
    [ -f $SECRETS/gsc_key.json ] && SC_KEY_FILE=$SECRETS/gsc_key.json
    # The scripts read either spelling of the service key.
    [ -n "${SUPABASE_SERVICE_KEY:-}" ] && SUPABASE_SERVICE_ROLE_KEY=$SUPABASE_SERVICE_KEY
    for k in "$@"; do
      [ -n "${!k:-}" ] && printf '%s=%q\n' "$k" "${!k}"
    done ) > "$tmp"
  install -o root -g "$group" -m 0640 "$tmp" "$ENVDIR/$name.env"
  rm -f "$tmp"
}
mkenv supabase  scraper SUPABASE_URL SUPABASE_SERVICE_KEY SUPABASE_SERVICE_ROLE_KEY
mkenv smtp      scraper SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD
mkenv apns      scraper APNS_KEY_PATH APNS_KEY_ID APNS_TEAM_ID APNS_TOPIC
mkenv gsc       scraper SC_KEY_FILE
mkenv typesafe  scraper TYPESAFE_API_KEY
mkenv nyc       scraper NYC_API_KEY
mkenv anthropic scraper ANTHROPIC_API_KEY AI_MONTHLY_CAP_MICROS
mkenv owner     scraper ERROR_REPORT_EMAIL GROWTH_REPORT_EMAIL
mkenv errors    facops  SUPABASE_URL SUPABASE_SERVICE_KEY SUPABASE_SERVICE_ROLE_KEY SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD ERROR_REPORT_EMAIL GROWTH_REPORT_EMAIL
# The old all-in-one file leaves the checkout; kept root-only for rollback.
[ -f $REPO/growth.env ] && mv -f $REPO/growth.env $ETC/growth.env.pre-20261007 && chmod 0600 $ETC/growth.env.pre-20261007

# ---------------------------------------------------------------- tools
say "fac-run, geoip, sudoers, logrotate"
install -o root -g root -m 0755 "$HERE/fac-run" /usr/local/bin/fac-run
install -o root -g root -m 0755 "$HERE/refresh_geoip.sh" /usr/local/sbin/fac-refresh-geoip
install -o root -g root -m 0440 "$HERE/sudoers-fac-jobs" /etc/sudoers.d/fac-jobs.new
visudo -cf /etc/sudoers.d/fac-jobs.new >/dev/null && mv -f /etc/sudoers.d/fac-jobs.new /etc/sudoers.d/fac-jobs
install -o root -g root -m 0644 "$HERE/logrotate-rentmap" /etc/logrotate.d/rentmap

# ---------------------------------------------------------------- venv + browsers out of the docroot
say "venv + browsers -> $OPT"
install -d -o root -g root -m 0755 $OPT
if [ -d $DOC/venv ] && [ ! -d $OPT/venv ]; then mv $DOC/venv $OPT/venv; fi
if [ -d /root/.cache/ms-playwright ] && [ ! -d $OPT/ms-playwright ]; then mv /root/.cache/ms-playwright $OPT/ms-playwright; fi
# flyer_reader.py used the API venv for these two; the job venv now has them.
$OPT/venv/bin/python -c 'import anthropic, pypdf' 2>/dev/null || \
  $OPT/venv/bin/python -m pip install -q "anthropic==$($API/venv/bin/python -c 'import anthropic;print(anthropic.__version__)')" \
                                         "pypdf==$($API/venv/bin/python -c 'import pypdf;print(pypdf.__version__)')"
chown -R root:root $OPT; chmod -R go-w $OPT

# ---------------------------------------------------------------- code + data out of the docroot
say "docroot cleanup"
# Scripts, a cert and caches that crons used to run from inside the web root.
# nginx already 404'd them; now they are simply not there. Parked, not deleted.
PARK=/root/docroot-parked-20261007
install -d -m 0700 $PARK
for f in $DOC/*.py $DOC/hcr_chain.pem $DOC/__pycache__ $DOC/scripts $DOC/vacancies.json; do
  [ -e "$f" ] && mv -f "$f" $PARK/
done

# ---------------------------------------------------------------- ownership
say "ownership"
chown -R scraper:scraper $REPO $BUILD $DOC
# The checkout stays world-readable: findacrib-api reads growth/*.json from it.
chmod -R go-w $REPO $BUILD
chmod 0755 $DOC
install -d -o facops -g facops -m 0750 /var/lib/findacrib
chown -R facops:facops /var/lib/findacrib
# Git push key for the ledger/re-rental commits: scraper's, no longer root's.
install -d -o scraper -g scraper -m 0700 /var/lib/scraper/.ssh
if [ -f /root/.ssh/id_findacrib ]; then
  mv -f /root/.ssh/id_findacrib /root/.ssh/id_findacrib.pub /var/lib/scraper/.ssh/
  cp /root/.ssh/known_hosts /var/lib/scraper/.ssh/known_hosts
  sed -i '/^Host findacrib.github.com/,/^$/d' /root/.ssh/config || true
fi
cat > /var/lib/scraper/.ssh/config <<'EOF'
Host findacrib.github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_findacrib
  IdentitiesOnly yes
EOF
chown -R scraper:scraper /var/lib/scraper/.ssh; chmod 0600 /var/lib/scraper/.ssh/*
# Same commit identity root's ledger commits used. Root never runs git inside
# the checkout again: it is scraper-writable, and .git/config can name programs.
for k in user.name user.email; do
  v=$(git config --global --get $k 2>/dev/null || true)
  [ -n "$v" ] && sudo -u scraper -H git config --global $k "$v"
done

# ---------------------------------------------------------------- logs
say "logs 0640"
for f in /var/log/rentmap-*.log; do
  case "$f" in
    */rentmap-errors.log) chown facops:adm "$f" ;;
    */rentmap-geoip.log)  chown root:adm "$f" ;;
    *)                    chown scraper:adm "$f" ;;
  esac
  chmod 0640 "$f"
done
# Locks the root-run jobs left behind in sticky /run/lock and /tmp.
for l in /run/lock/fac-alerts.lock /run/lock/fac-browser.lock /tmp/findacrib-refresh-seo.lock; do
  [ -e "$l" ] && [ "$(stat -c %U "$l")" = root ] && flock -n "$l" rm -f "$l" || true
done

# ---------------------------------------------------------------- cron
say "cron.d"
for f in "$HERE"/cron-rentmap-*; do
  n=$(basename "$f"); n=${n#cron-}
  install -o root -g root -m 0644 "$f" /etc/cron.d/$n
done
# Guard: no rentmap job line may run as root except the GeoIP download.
if grep -hE '^[^#A-Z].* root ' /etc/cron.d/rentmap-* | grep -v fac-refresh-geoip; then
  echo "!! a rentmap cron line still runs as root" >&2; exit 1
fi
say "done"
