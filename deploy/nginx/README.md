# nginx config snapshot

These files are a read-only snapshot of the nginx configuration that actually
serves findacrib.com. Until 2026-11-10 the vhost existed only on the droplet,
so a rebuild or a migration had no tracked copy to restore from.

Taken from `root@142.93.183.172` (hostname `findacrib`) on **2026-11-10**.

| Snapshot | Live path |
|---|---|
| `sites-available/findacrib.conf` | `/etc/nginx/sites-available/findacrib` |
| `sites-available/default-drop.conf` | `/etc/nginx/sites-available/default-drop` |
| `conf.d/ratelimit.conf` | `/etc/nginx/conf.d/ratelimit.conf` |
| `conf.d/log_format_site.conf` | `/etc/nginx/conf.d/log_format_site.conf` |

`sites-enabled/findacrib` and `sites-enabled/default-drop` are symlinks to the
`sites-available` files above.

## Deliberately not tracked

- `conf.d/findacrib_blocked_asn.conf` — a ~26 KB generated list of blocked
  ASN ranges, refreshed from an external source. A snapshot would be stale
  within days; the vhost only needs the map to exist. On a fresh box, create
  the stub in the restore section below before `nginx -t`.
- `/etc/letsencrypt/options-ssl-nginx.conf` and the certificate paths — certbot
  owns those and rewrites them on renewal.
- `default-drop.conf` returns 444 / rejects TLS for any hostname this box does
  not serve. It is small, stable, and worth having on a rebuild, so it is
  tracked.

## Checking for drift

```sh
scripts/check_nginx_drift.sh
```

The script reads each live file over SSH and diffs it against this directory.
It exits non-zero on any difference, so it can run in a pre-deploy check or a
weekly cron. `FAC_HOST` overrides the default `root@142.93.183.172`.

## Restoring after a rebuild

Copy the files back to their live paths, then validate before reloading:

```sh
# The vhost references $fac_blocked_asn from conf.d/findacrib_blocked_asn.conf,
# which is not tracked. A stub lets nginx start; the real list is generated
# separately (see that file's header for the RIPEstat source).
printf 'geo $fac_blocked_asn {\n    default 0;\n}\n' \
  | sudo tee /etc/nginx/conf.d/findacrib_blocked_asn.conf
sudo nginx -t && sudo systemctl reload nginx
```

Do not copy `findacrib.conf` over a working vhost without checking the
`ssl_certificate` lines: certbot may have renewed the certificate since this
snapshot was taken.
