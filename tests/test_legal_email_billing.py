"""Legal fixes of 2026-11-07 (owner: "fix this").

CAN-SPAM: every email emailkit builds carries the postal address, and every
promotional/alert email carries a one-click unsubscribe that reaches a server
(a findacrib.com/#unsub= fragment never did). California's auto-renewal law
and ROSCA: web Plus can be cancelled online (billing-portal), the paywall and
Stripe Checkout state the renewal terms, and a reminder goes out before a
trial converts (stripe-webhook -> billing_notices -> billing_notices.py).
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from growth import emailkit  # noqa: E402

ADDRESS = "251 Dekalb Ave, Brooklyn, NY 11205"
TOKEN = "11111111-2222-3333-4444-555555555555"


def read(*p):
    return (ROOT.joinpath(*p)).read_text()


class PostalFooter(unittest.TestCase):
    def test_render_html_and_text_carry_the_address(self):
        html, text = emailkit.render(title="t", blocks=[{"type": "note", "text": "x"}])
        self.assertIn(ADDRESS, html)
        self.assertIn(ADDRESS, text)

    def test_render_with_unsubscribe_keeps_both(self):
        html, text = emailkit.render(title="t", footer_note="why", unsub_url="https://findacrib.com/u")
        self.assertIn(ADDRESS, html)
        self.assertIn("https://findacrib.com/u", html)
        self.assertTrue(text.rstrip().endswith(emailkit.POSTAL), text[-200:])
        self.assertIn("Unsubscribe: https://findacrib.com/u", text)

    def test_render_alert_html_and_text_carry_the_address(self):
        html, text = emailkit.render_alert(title="t", blocks=[{"type": "note", "text": "x"}],
                                           unsub_url="https://findacrib.com/u")
        self.assertIn(ADDRESS, html)
        self.assertIn(ADDRESS, text)

    def test_postal_text_is_the_one_constant(self):
        self.assertEqual(emailkit.postal_text(), "Find A Crib · " + ADDRESS)


class OneClickUnsubscribe(unittest.TestCase):
    def test_account_unsub_url_reaches_the_api(self):
        u = emailkit.account_unsub_url(TOKEN, "digest")
        self.assertEqual(u, f"https://findacrib.com/api/email/unsubscribe?k=digest&t={TOKEN}")
        self.assertNotIn("#", u)

    def test_no_sender_puts_a_fragment_in_list_unsubscribe(self):
        # The header url is what one-click POSTs to; a #fragment never reaches
        # a server. Saved alerts and the account series used to do exactly that.
        for f in ("saved_alerts.py", "growth/accounts.py"):
            src = read(f)
            self.assertNotRegex(src, r'f"\{SITE\}/#unsub=', f)
            self.assertIn("account_unsub_url(", src, f)

    def test_api_route_get_never_unsubscribes_post_does(self):
        src = read("api_server.py")
        i = src.index('@app.route("/email/unsubscribe"')
        body = src[i:src.index("\n@app.route", i + 10)]
        self.assertIn('methods=["GET", "POST"]', body)
        get_branch = body[body.index('if request.method == "GET"'):body.index("rate_limited(")]
        self.assertNotIn("rpc(", get_branch, "a GET (mail scanners) must never unsubscribe")
        self.assertIn('rate_limited("email_unsub"', body)
        self.assertIn("TOKEN_RE.match(token)", body)
        # The /v1 API-key gate must let it through, or every click is a 401
        # (it was, on the first deploy, 2026-11-07).
        gate = src[src.index("def gate():"):src.index("return", src.index("def gate():"))]
        self.assertIn('request.path == "/email/unsubscribe"', gate)
        for kind, fn in (("alerts", "unsubscribe_alerts"), ("digest", "unsubscribe_digest"),
                         ("lifecycle", "unsubscribe_lifecycle"), ("casa", "unsubscribe_casa")):
            self.assertIn(f'"{kind}": "{fn}"', src)

    def test_unsubscribe_casa_is_service_role_only(self):
        sql = read("db", "0074_billing_notices_casa_unsub.sql")
        self.assertIn("create or replace function public.unsubscribe_casa(p_token uuid)", sql)
        self.assertIn("revoke execute on function public.unsubscribe_casa(uuid) from public, anon, authenticated", sql)
        self.assertIn("grant execute on function public.unsubscribe_casa(uuid) to service_role", sql)

    def test_casa_alerts_send_the_header(self):
        src = read("casa_alerts.py")
        self.assertIn('emailkit.send(w["email"], subject, html, text, unsub_url=w.get("unsub"))', src)
        self.assertIn('account_unsub_url(tok[w["user_id"]], "casa")', src)

    def test_casa_attach_unsub_uses_the_alert_prefs_token(self):
        import casa_alerts
        calls = []
        orig = casa_alerts.rest
        casa_alerts.rest = lambda path, key, *a, **k: (calls.append(path) or
                                                        [{"user_id": "u1", "token": TOKEN}])
        try:
            ws = [{"user_id": "u1"}, {"user_id": "u2"}]
            casa_alerts.attach_unsub(ws, "k")
        finally:
            casa_alerts.rest = orig
        self.assertTrue(calls[0].startswith("alert_prefs?select=user_id,token&user_id=in.("))
        self.assertEqual(ws[0]["unsub"], emailkit.account_unsub_url(TOKEN, "casa"))
        self.assertNotIn("unsub", ws[1])

    def test_founding_members_blast_is_opt_outable(self):
        import founding_members as fm
        text, html, unsub = fm.build(TOKEN)
        self.assertEqual(unsub, emailkit.account_unsub_url(TOKEN, "lifecycle"))
        for part in (text, html):
            self.assertIn(ADDRESS, part)
            self.assertIn("Unsubscribe", part)
        src = read("founding_members.py")
        self.assertIn('msg["List-Unsubscribe"]', src)
        self.assertIn('msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"', src)
        self.assertIn('not r.get("opted_out")', src)

    def test_comp_campaign_is_opt_outable_and_keeps_emails_out_of_git(self):
        import comp_campaign as cc
        subject, text, html, unsub = cc.build("abc123", TOKEN)
        self.assertEqual(unsub, emailkit.account_unsub_url(TOKEN, "lifecycle"))
        for part in (text, html):
            self.assertIn(ADDRESS, part)
            self.assertIn("Unsubscribe", part)
            self.assertNotIn("caprecruiting", part)
            self.assertNotRegex(part.lower(), r"\bfree\b")  # FAC copy rule
        self.assertNotRegex(subject.lower(), r"\bfree\b")
        src = read("comp_campaign.py")
        self.assertIn('msg["List-Unsubscribe"]', src)
        self.assertIn('msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"', src)
        self.assertIn('r.get("opted_out")', src)
        # Recipients come from a gitignored file, never from the source.
        code = src.split('"""', 2)[2]
        self.assertNotRegex(code, r"[\w.+-]+@gmail\.com")
        gi = read(".gitignore")
        self.assertIn("comp_recipients*.txt", gi)
        self.assertIn("comp_sent.json", gi)

    def test_hand_built_user_mail_is_gone_or_footed(self):
        # Any script that mails a user without emailkit.render must say how it
        # carries the address. Owner-only reports are listed as exempt.
        owner_only = {"check_dhcr_list.py", "seo_health.py", "seo_search_console.py",
                      "traffic_report.py", "monitoring/uptime_watch.py"}
        for path in [*ROOT.glob("*.py"), *ROOT.glob("growth/*.py"), *ROOT.glob("monitoring/*.py")]:
            rel = str(path.relative_to(ROOT))
            src = path.read_text(errors="ignore")
            if "smtplib.SMTP" not in src or rel == "growth/emailkit.py" or rel in owner_only:
                continue
            self.assertIn("emailkit.", src, f"{rel} sends mail by hand: route it through emailkit "
                                            "or add the postal address + unsubscribe, then list it here")


class BillingNotices(unittest.TestCase):
    def test_trial_reminder_says_amount_date_and_how_to_cancel(self):
        import billing_notices as bn
        subject, html, text = bn.build({"trial_end": "2026-11-26T09:49:04+00:00", "amount_cents": 499,
                                        "currency": "usd", "interval": "month"})
        self.assertIn("Nov 26", subject)
        self.assertIn("$4.99", subject)
        for part in (html, text):
            self.assertIn("$4.99", part)
            self.assertIn("November 26, 2026", part)
            self.assertIn("4:49 AM ET", part)
            self.assertIn("Manage or cancel Plus", part)
            self.assertIn("https://findacrib.com/#manage-plus", part)
            self.assertIn(ADDRESS, part)
            self.assertNotIn("Unsubscribe", part)   # transactional

    def test_reminder_never_waits_for_the_daily_mail_cap(self):
        src = read("billing_notices.py")
        self.assertNotIn("mailcap.claim", src.replace("Deliberately no mailcap.claim()", ""))

    def test_webhook_records_trial_will_end(self):
        src = read("supabase", "functions", "stripe-webhook", "index.ts")
        self.assertIn('event.type === "customer.subscription.trial_will_end"', src)
        self.assertIn('from("billing_notices").upsert(', src)
        self.assertIn('onConflict: "stripe_subscription_id,trial_end,kind", ignoreDuplicates: true', src)
        self.assertIn("sub.cancel_at_period_end", src)
        # Cancelled before the reminder went out: the pending row is closed.
        self.assertIn("await closeStaleNotices(event.data.object)", src)

    def test_billing_notices_table_is_service_role_only(self):
        sql = read("db", "0074_billing_notices_casa_unsub.sql")
        self.assertIn("revoke all on public.billing_notices from public, anon, authenticated", sql)
        self.assertIn("enable row level security", sql)

    def test_cron_runs_it_without_root(self):
        cron = read("deploy", "cron-rentmap-billing")
        line = [l for l in cron.splitlines() if l and not l.startswith(("#", "SHELL", "PATH", "CRON_TZ"))][0]
        self.assertRegex(line, r"^\*/10 \* \* \* \* scraper .*flock -n /run/lock/fac-billing.lock fac-run supabase,smtp -- .*billing_notices\.py")
        self.assertIn("/var/log/rentmap-billing.log", read("deploy", "install_jobs.sh"))
        self.assertIn("/var/log/rentmap-billing.log", read("deploy", "logrotate-rentmap"))


class OnlineCancel(unittest.TestCase):
    def test_portal_takes_the_customer_from_the_session_only(self):
        src = read("supabase", "functions", "billing-portal", "index.ts")
        self.assertIn("supabase.auth.getUser()", src)
        self.assertIn('.eq("user_id", user.id)', src)
        self.assertIn("customer,", src)
        # The body is read only for return_url: no customer from the client.
        self.assertRegex(src, r"const \{ return_url \} = await req\.json\(\)")
        self.assertNotRegex(src, r"\b(body|json)\.customer\b")
        self.assertIn("safeReturn(return_url)", src)
        self.assertIn('"https://findacrib.com"', src)
        self.assertIn("limited(user.id)", src)
        self.assertRegex(src, r'PORTAL_CONFIG = .*"bpc_[A-Za-z0-9]+"')

    def test_portal_function_keeps_its_own_auth(self):
        cfg = read("supabase", "config.toml")
        self.assertIn("[functions.billing-portal]", cfg)

    def test_page_offers_cancel_and_states_renewal_terms(self):
        html = read("index.html")
        self.assertIn('id="profile-manage-plus"', html)
        self.assertIn(">Manage or cancel Plus</button>", html)
        self.assertIn("Settings › Apple Account › Subscriptions", html)
        self.assertIn("invoke('billing-portal'", html)
        self.assertIn('href="#manage-plus" id="profile-delete-manage"', html)
        fine = re.search(r'<p class="paywall-fine" id="paywall-fine">(.*?)</p>', html).group(1)
        for must in ("$4.99", "30 days", "renews automatically every month until you cancel",
                     "Manage or cancel Plus"):
            self.assertIn(must, fine)

    def test_checkout_page_states_renewal_and_cancel(self):
        src = read("supabase", "functions", "create-checkout", "index.ts")
        self.assertIn('"custom_text[submit][message]"', src)
        for must in ("$4.99/month", "until you cancel", "Manage or cancel Plus", "30 days"):
            self.assertIn(must, src)


if __name__ == "__main__":
    unittest.main()
