# Traffic report

Moved from the README on 2026-11-06. Back to the [README](../README.md).


`traffic_report.py` prints a traffic dashboard from the Supabase `visits` /
`events` logs: today's numbers, a month-to-month table, the last 14 days,
new-vs-returning, week-over-week retention, and today's activity breakdown. The
owner's own visits are always excluded. Needs the Supabase PAT in the macOS
keychain (`supabase-pat-clockin`).

```sh
python3 traffic_report.py                      # dashboard
python3 traffic_report.py --json               # raw JSON
python3 traffic_report.py --email a@b.com      # email the dashboard
```

Emailing uses `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` from the
environment. A weekly cron on the caprecruiting droplet (167.71.170.219,
`/root/findacrib-report/`) mails this to the owner every Monday 8am ET.

