#!/usr/bin/env python3
"""Building chat on findacrib.com, end to end, with two real accounts.

Two throwaway accounts (internal, deleted at the end — that cascades their
members/devices/messages rows) open the same building's chat in two browsers:
both join, A types and B sees A's typing bubble, A sends and B reads it
(decrypted in B's browser with B's own device key), B replies and A reads it;
B reacts, A replies with a quote, A unsends it and it leaves B's room live.
The page under test is the LOCAL casa/index.html + static/chat/*, routed in
place of findacrib.com, against the live database and Realtime.

    python3 tests/web_chat_e2e.py [--engine chromium|webkit] [--headed] [--target local|live]

The secret key comes from the Management API (keychain PAT) and stays in memory.
"""
import argparse
import json
import pathlib
import secrets
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
REF = "dbaifotzwlxjvsxjohjt"
URL = f"https://{REF}.supabase.co"
LIVE = "https://findacrib.com"
# A real lot (Your Crib's own demo building) — rows the test writes are only
# readable by its own two accounts, and are deleted with them.
PLACE = {"label": "9 Dekalb Ave, Brooklyn, New York", "bbl": "3001497503", "lat": 40.6905, "lng": -73.9845}


def http(url, method="GET", body=None, headers=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "User-Agent": "curl/8.7.1", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def keys():
    pat = subprocess.check_output(["security", "find-generic-password", "-s", "supabase-pat-clockin", "-w"]).decode().strip()
    ks = http(f"https://api.supabase.com/v1/projects/{REF}/api-keys?reveal=true", headers={"Authorization": f"Bearer {pat}"})
    by = {k["name"]: k["api_key"] for k in ks}
    # The dedicated keys since the 2026-10-25 rotation; the legacy JWT keys
    # are on their way to being disabled.
    return by["fac_secret"], by["fac_publishable"]


def make_user(service, anon, tag):
    email, pw = f"chat-e2e-{tag}-{secrets.token_hex(4)}@example.com", secrets.token_urlsafe(18)
    u = http(f"{URL}/auth/v1/admin/users", "POST", {"email": email, "password": pw, "email_confirm": True,
                                                    "user_metadata": {"internal": True}},
             {"apikey": service, "Authorization": f"Bearer {service}"})
    sess = http(f"{URL}/auth/v1/token?grant_type=password", "POST", {"email": email, "password": pw}, {"apikey": anon})
    return u["id"], sess


def route_local(page):
    def handle(r):
        u = r.request.url.split("#")[0].split("?")[0]
        if u in (LIVE + "/casa/", LIVE + "/casa/index.html"):
            r.fulfill(status=200, content_type="text/html; charset=utf-8", body=(ROOT / "casa" / "index.html").read_text())
        elif u.startswith(LIVE + "/static/chat/"):
            f = ROOT / "static" / "chat" / u.rsplit("/", 1)[-1]
            r.fulfill(status=200, content_type="text/css" if f.suffix == ".css" else "application/javascript", body=f.read_text())
        else:
            r.continue_()
    page.route(LIVE + "/**", handle)


def open_chat(browser, sess, name, local):
    ctx = browser.new_context(viewport={"width": 1200, "height": 900})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    if local:
        route_local(page)
    store = {f"sb-{REF}-auth-token": json.dumps(sess), "fac.casa": json.dumps(PLACE), "fac.chat.name": name}
    page.add_init_script("(() => { const s = %s; for (const k in s) localStorage.setItem(k, s[k]); })()" % json.dumps(store))
    page.goto(LIVE + "/casa/", wait_until="domcontentloaded")
    page.locator("#chat-btn").click()
    page.locator("[data-testid=chat-terms]").check(timeout=20000)
    page.locator("[data-testid=chat-join]").click()
    page.locator("[data-testid=chat-input]").wait_for(timeout=20000)
    return page, errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="chromium", choices=["chromium", "webkit"])
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--target", default="local", choices=["local", "live"])
    a = ap.parse_args()
    service, anon = keys()
    admin = {"apikey": service, "Authorization": f"Bearer {service}"}
    users = []
    failures = []
    def check(ok, what):
        print(("ok   " if ok else "FAIL ") + what)
        if not ok: failures.append(what)
    try:
        ua, sa = make_user(service, anon, "a"); users.append(ua)
        ub, sb = make_user(service, anon, "b"); users.append(ub)
        with sync_playwright() as p:
            browser = getattr(p, a.engine).launch(headless=not a.headed)
            pa, ea = open_chat(browser, sa, "Alex, 3C", a.target == "local")
            pb, eb = open_chat(browser, sb, "Bea", a.target == "local")
            time.sleep(3)                       # both typing channels subscribed
            pa.locator("[data-testid=chat-input]").press_sequentially("hey neighbor", delay=60)
            typing = pb.locator("[data-testid=chat-typing]")
            try:
                typing.wait_for(timeout=10000); check(True, "B sees A's typing bubble")
            except Exception:
                check(False, "B sees A's typing bubble")
            pa.locator("[data-testid=chat-input]").press("Enter")
            got = pb.locator("[data-testid=chat-message]", has_text="hey neighbor")
            try:
                got.wait_for(timeout=15000); check(True, "B reads A's message, decrypted in B's browser")
            except Exception:
                check(False, "B reads A's message, decrypted in B's browser")
            check(pb.locator("[data-testid=chat-typing]").count() == 0, "A's bubble goes when the message lands")
            pb.locator("[data-testid=chat-input]").fill("hi Alex")
            pb.locator("[data-testid=chat-input]").press("Enter")
            try:
                pa.locator("[data-testid=chat-message]", has_text="hi Alex").wait_for(timeout=15000)
                check(True, "A reads B's reply")
            except Exception:
                check(False, "A reads B's reply")
            # Instagram layout (2026-10-23): yours right, theirs left, no "You".
            mine = pa.locator("[data-testid=chat-message]", has_text="hey neighbor").bounding_box()
            theirs = pa.locator("[data-testid=chat-message]", has_text="hi Alex").bounding_box()
            check(mine and theirs and mine["x"] > theirs["x"] + 100, "yours sit right, a neighbor's left")
            whos = pa.locator(".fc-who").all_inner_texts()
            check("Bea" in whos and "You" not in whos, f"a neighbor's run is named, yours isn't ({whos})")
            check(pa.locator("[data-testid=chat-stamp]").first.inner_text().lower().startswith("today"), "a centred Today time line")
            # B reacts to A's message from the hold menu; A sees it live.
            pb.locator("[data-testid=chat-message]", has_text="hey neighbor").click(button="right")
            pb.locator("[data-testid=chat-react-🔥]").click()
            try:
                pa.locator("[data-testid=chat-reactions]").wait_for(timeout=15000)
                check("🔥" in pa.locator("[data-testid=chat-reactions]").first.inner_text(), "A sees B's reaction under the message")
            except Exception:
                check(False, "A sees B's reaction under the message")
            check(pb.locator("[data-testid=chat-message]").count() == 2, "a reaction isn't a message of its own")
            # A replies to B's message; B sees the quote.
            pa.locator("[data-testid=chat-message]", has_text="hi Alex").click(button="right")
            pa.locator("[data-testid=chat-menu-reply]").click()
            check(pa.locator("[data-testid=chat-replying]").is_visible(), "Reply opens the Replying to bar")
            pa.locator("[data-testid=chat-input]").fill("same here")
            pa.locator("[data-testid=chat-input]").press("Enter")
            try:
                pb.locator("[data-testid=chat-quote]", has_text="hi Alex").wait_for(timeout=15000)
                check(True, "B sees A's reply quoting B's message")
            except Exception:
                check(False, "B sees A's reply quoting B's message")
            # A unsends it; it leaves B's room live.
            pa.locator("[data-testid=chat-message]", has_text="same here").click(button="right")
            check(pa.locator("[data-testid=chat-menu-unsend]").is_visible(), "Unsend on your own message")
            pa.locator("[data-testid=chat-menu-unsend]").click()
            try:
                pb.locator("[data-testid=chat-message]", has_text="same here").wait_for(state="detached", timeout=15000)
                check(True, "an unsent message leaves the other browser live")
            except Exception:
                check(False, "an unsent message leaves the other browser live")
            # Details from the menu: a side panel when wide, a sheet when narrow.
            pa.locator("[data-testid=chat-message]", has_text="hi Alex").click(button="right")
            pa.locator("[data-testid=chat-menu-details]").click()
            check(pa.locator("[data-testid=chat-detail]").is_visible(), "Details reveals a message's details")
            check(pa.locator("[data-testid=chat-detail-report]").is_visible(), "with Report, for someone else's message")
            box = pa.locator("[data-testid=chat-detail]").bounding_box()
            check(box and box["width"] <= 320 and box["x"] > 600, "a wide chat shows details in a side panel")
            pa.set_viewport_size({"width": 390, "height": 844})
            time.sleep(0.4)
            box = pa.locator("[data-testid=chat-detail]").bounding_box()
            check(box and box["width"] > 350, "a narrow chat shows them as a sheet")
            pa.screenshot(path=f"/tmp/web_chat_{a.engine}.png")
            check(not ea and not eb, f"no page errors ({ea + eb})")
            browser.close()
    finally:
        for uid in users:
            try: http(f"{URL}/auth/v1/admin/users/{uid}", "DELETE", headers=admin)
            except Exception as e: print(f"cleanup {uid}: {e}")
    print(f"{'FAILED' if failures else 'passed'}: web chat e2e ({a.engine}, {a.target})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
