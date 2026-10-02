#!/usr/bin/env python3
"""Outside-in uptime check for every product site, every 5 minutes.

error_report.py runs ON the findacrib droplet, so the one failure it can
never report is that droplet going down. This runs on the OTHER droplets:
each box checks every site that is NOT hosted on itself (by comparing the
site's DNS answer with the box's own addresses), so 104 watches 159's sites
and 159 watches everyone else's.

Two failures in a row (~10 min) send one "DOWN" email; the first success
after that sends "back up". State: /var/lib/uptime-watch/state.json.
SMTP settings come from /etc/uptime-watch.env (SMTP_HOST/PORT/USER/PASSWORD,
ALERT_TO). Deployed by monitoring/deploy_uptime_watch.sh.
"""
from __future__ import annotations

import json
import os
import smtplib
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from email.message import EmailMessage
from pathlib import Path

# (url, text the body must contain — None for status-only)
SITES = [
    ("https://findacrib.com/", "Find A Crib"),
    ("https://findacrib.com/api/geo", '"lat"'),
    ("https://creasenyc.com/", None),
    ("https://nemoseamlessgutter.com/", None),
    ("https://haukley.com/", None),
    ("https://rawchella.com/", None),
    ("https://marracat.com/", None),
    ("https://caprecruiting.com/", None),
    ("https://sputterbets.com/", None),
    ("https://divinedavis.com/", None),
]
STATE = Path("/var/lib/uptime-watch/state.json")
FAILS_TO_ALERT = 2


def env() -> dict:
    out = {}
    for line in Path("/etc/uptime-watch.env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def own_ips() -> set[str]:
    return set(subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split())


def check(url: str, needle: str | None) -> str | None:
    """None when healthy, else a one-line reason."""
    req = urllib.request.Request(url, headers={"User-Agent": "uptime-watch/1"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read(400_000).decode("utf-8", "replace")
            if needle and needle not in body:
                return f"HTTP {r.status} but the page is missing {needle!r}"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except Exception as e:  # timeouts, DNS, TLS, refused
        return f"{type(e).__name__}: {e}"[:200]
    if time.time() - t0 > 15:
        return f"slow: {time.time() - t0:.0f}s"
    return None


def send(cfg: dict, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, cfg["SMTP_USER"], cfg["ALERT_TO"]
    msg.set_content(body)
    port = int(cfg.get("SMTP_PORT") or 465)
    if port == 465:
        with smtplib.SMTP_SSL(cfg["SMTP_HOST"], port, context=ssl.create_default_context(), timeout=30) as s:
            s.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"]); s.send_message(msg)
    else:
        with smtplib.SMTP(cfg["SMTP_HOST"], port, timeout=30) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"]); s.send_message(msg)


def main() -> None:
    cfg, mine = env(), own_ips()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    box = socket.gethostname()
    for url, needle in SITES:
        host = url.split("/")[2]
        try:
            if socket.gethostbyname(host) in mine:
                continue  # can't watch yourself — the other droplet does
        except OSError:
            pass  # DNS failing is exactly what check() should report
        s = state.setdefault(url, {"fails": 0, "alerted": False})
        why = check(url, needle)
        if why is None:
            if s["alerted"]:
                send(cfg, f"UP again: {host}", f"{url} is answering again (checked from {box}).")
            state[url] = {"fails": 0, "alerted": False}
            continue
        s["fails"] += 1
        s["last"] = why
        if s["fails"] >= FAILS_TO_ALERT and not s["alerted"]:
            send(cfg, f"DOWN: {host}", f"{url} failed {s['fails']} checks in a row, 5 min apart.\n"
                 f"Latest: {why}\nChecked from {box}. You'll get one more email when it's back.")
            s["alerted"] = True
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1))


if __name__ == "__main__":
    if "--test-email" in os.sys.argv:
        send(env(), "uptime-watch: test", f"Test from {socket.gethostname()} — alerts reach you.")
    else:
        main()
