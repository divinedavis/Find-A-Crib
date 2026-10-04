#!/usr/bin/env python3
"""The Marracat tab's Find A Crib-style tiles, trend and investor card render
from a Marracat payload (owner, 2026-10-04). Synthetic data, no network.

Run with ~/.venvs/dhcr-map/bin/python tests/dashboard_marracat.py [screenshot.png]
"""
import sys
from playwright.sync_api import expect, sync_playwright
from dashboard_auth import BASE, ROOT, USER, callback

PAYLOAD = {
    "__site__": "marracat", "ok": True, "range": "all", "generated_at": "2026-10-04T22:00:00Z", "log_since": "2026-09-20",
    "app": {"devices": 4, "launches": 16, "owner_devices_excluded": 67}, "web": {"visitors": 96, "product_views": 120},
    "shoppers": {"accounts": 10, "new": 4, "orders": 2, "items": 3, "gmv_usd": 140.5, "brands": 2, "buyers": 2,
                 "providers": {"apple": 6, "google": 4}},
    "visits": {"visitors": 50, "returning": 12, "web": 46, "app": 4}, "restock": {"signups": 3, "alerts_sent": 1},
    "late": {"brands": [], "reports": 0}, "performance": [],
    "fac": {"visits_since": "2026-10-04",
            "engagement": {"mau": 50, "mau_prior": 40, "wau": 20, "wau_prior": 25, "dau_7d_mean": 6, "stickiness": 0.12, "app_actives_30d": 4},
            "retention": {"d1": {"cohort": 30, "returned": 6, "rate": 0.2}, "d7": {"cohort": 20, "returned": 5, "rate": 0.25},
                          "d30": {"cohort": 0, "returned": 0, "rate": None}},
            "sources": {"direct": 20, "search": 10, "social": 8, "referral": 2, "tagged": 5, "app": 5, "new": 50, "organic_share": 0.4},
            "growth": {"new_30d": 4, "new_prior_30d": 0, "all_time": 10},
            "daily_series": [{"date": "2026-10-0%d" % i, "visitors": i * 3, "signups": i % 2} for i in range(1, 5)]},
}


def main(shot=None):
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_context(viewport={"width": 1440, "height": 2200}).new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route(BASE + "/dashboard/", lambda r: r.fulfill(path=str(ROOT / "dashboard/index.html"), content_type="text/html"))
        for path in ("config.js", "static/supabase/supabase.js"):
            page.route(BASE + "/" + path, lambda r, req, path=path: r.fulfill(path=str(ROOT / path), content_type="application/javascript"))
        page.route("**/auth/v1/user", lambda r: r.fulfill(json=USER))
        page.route("**/api/dashboard-*", lambda r: r.fulfill(json=PAYLOAD))
        page.goto(BASE + "/dashboard/" + callback(), wait_until="networkidle")
        page.locator('button.site-btn[data-site="marracat"]').click()
        page.wait_for_timeout(1500)
        tiles = page.locator("#tiles")
        for text in ["Unique visitors", "100", "Returning visitors · this range", "12 · 24%", "Sign-up conversion", "4.0%",
                     "Restock alert sign-up conversion", "3.0%", "Sales sent to brands", "$140.50", "Buyer conversion", "20.0%"]:
            expect(tiles).to_contain_text(text)
        inv = page.locator("#mc-investor")
        for text in ["Monthly actives", "+25%", "Retention", "20.0% · 25.0% · —", "40.0% organic", "Stickiness", "12.0%"]:
            expect(inv).to_contain_text(text)
        expect(page.locator("#mc-trend svg")).to_have_count(2)
        expect(page.locator("#mc-downloads")).to_contain_text("requested on 4 Oct 2026")
        if shot:
            page.screenshot(path=shot, full_page=False)
        assert not errors, errors
        b.close()
    print("PASS marracat tab: tiles, investor card, trend, downloads")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
