# Production layout

Verified on **2026-11-10** against the live droplet, not copied from notes.
Re-check with the commands at the bottom before trusting this after a move.

## The box

| | |
|---|---|
| Hostname | `findacrib` |
| Address | `142.93.183.172` (the only A record for `findacrib.com` and `www`) |
| SSH | `root@142.93.183.172` |
| Serves | findacrib.com only; every other hostname gets 444 / TLS rejected |

`142.93.183.172` replaced the shared `104.236.120.144` box on 2026-10-07
(commit `2755fe5e`). The old box still exists and still has a
`/var/www/rent-map` docroot, but DNS does not point at it. If a deploy seems to
vanish, check which host the script used before debugging the page.

## Paths

| Path | Size on 2026-11-10 | What it is |
|---|---:|---|
| `/var/www/rent-map` | 1.2 GB | Live docroot: `index.html`, city pages, `static/`, the generated SEO corpus, and the API's JSON data |
| `/root/findacrib-api` | 222 MB | The running API. **Not a git checkout**; updated only by `scripts/deploy_api.sh`. Holds its own `.env`, venv and `.cache` |
| `/root/dhcr-build` | 998 MB | The nightly SEO build checkout. `scripts/refresh_seo.sh` builds here and rsyncs `seo/` into the docroot |
| `/etc/cron.d/rentmap-*` | 24 files | Installed from `deploy/`; see `deploy/install_jobs.sh` |
| `/etc/nginx/sites-enabled/findacrib` | 296 lines | The vhost. Tracked as a snapshot in `deploy/nginx/` |
| `/etc/nginx/sites-enabled/default-drop` | 18 lines | 444 / TLS-reject for unknown hostnames |
| `/var/lib/findacrib-api` | — | API caches, owned by the unprivileged `findacrib` user |
| `/var/backups/findacrib-app` | — | Last 15 app-shell snapshots, written by `deploy_app.sh` |

## Deploy paths

| What | How |
|---|---|
| App shell (`index.html`, city pages, a few `static/` files) | `scripts/deploy_app.sh` — unit tests + local journeys, snapshot, scp, live journeys, rollback on failure |
| API (`api_server.py` and its modules) | `scripts/deploy_api.sh` — copies into `/root/findacrib-api`, restarts gunicorn, health-checks |
| City data (`sf/`, `la/`, `dc/`, `westchester/`) | `scripts/deploy_city_data.sh` |
| SEO pages (~47.6k) | Nightly `scripts/refresh_seo.sh` **on the droplet**, from `/root/dhcr-build` |
| Owner dashboard | Separate repo (`owner-dashboard`) and separate droplet, not this one |

One writer per file: do not add the hand-authored `/developers/`, `/embed/` or
`/marketing-agents/` pages to `deploy_app.sh`; they ride the SEO rsync.

## Drift checks

```sh
# nginx: tracked snapshot vs live
scripts/check_nginx_drift.sh

# app shell: is the live page the one in this checkout?
ssh root@142.93.183.172 'sha256sum /var/www/rent-map/index.html'
shasum -a 256 index.html

# API: is the running copy the one in this checkout?
ssh root@142.93.183.172 'sha256sum /root/findacrib-api/api_server.py'
shasum -a 256 api/api_server.py
```

The live shell is allowed to be ahead of a checkout that has not fetched or
deployed yet. It is not allowed to be ahead of `origin/main` for long: that
means a deploy ran from an unmerged worktree and the source of truth is
missing a change.
