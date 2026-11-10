"""Browser notifications are wired end to end (2026-11-10): the jobs that
push to phones also push to browsers, they are given the keys to, the API
ships webpush.py, and its routes take the account from the session."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*p):
    with open(os.path.join(ROOT, *p)) as f:
        return f.read()


class Wiring(unittest.TestCase):
    def test_the_alert_jobs_get_the_webpush_keys(self):
        self.assertIn("mkenv webpush   scraper WEB_PUSH_PUBLIC_KEY WEB_PUSH_PRIVATE_KEY WEB_PUSH_SUBJECT", read("deploy", "install_jobs.sh"))
        for cron, job in (("cron-rentmap-alerts", "lottery_alerts.sh"), ("cron-rentmap-casa", "casa_alerts.sh")):
            lines = [l for l in read("deploy", cron).splitlines() if job in l and not l.startswith("#")]
            self.assertTrue(lines, cron)
            for line in lines:
                self.assertRegex(line, r"fac-run [a-z,]*\bwebpush\b", line)

    def test_the_jobs_that_push_to_phones_push_to_browsers(self):
        lottery = read("lottery_alerts.py")
        self.assertIn('rpc("web_push_for_emails"', lottery)
        self.assertIn("webpush.send(b, webpush.note(title, text_body", lottery)
        self.assertIn('rpc("web_push_remove"', lottery)
        self.assertIn("if is_plus and (phones or screens) and to_push:", lottery,
                      "a Plus member with only a browser still gets the real-time alert when the email waits")
        self.assertIn("webpush.push_to_emails(la.rpc, key, [w[\"email\"]]", read("casa_alerts.py"))

    def test_the_api_ships_webpush_and_trusts_only_the_session(self):
        self.assertRegex(read("scripts", "deploy_api.sh"), r"FILES=\([^)]*\bwebpush\.py\b")
        api = read("api_server.py")
        fn = api[api.index("def push_web_subscribe():"):]
        fn = fn[:fn.index("\n# ---- ")]
        self.assertIn("u = _session_user()", fn)
        self.assertIn('"p_user_id": u["id"]', fn)
        self.assertIn('rpc("web_push_remove_own"', fn)
        self.assertIn("webpush.push_endpoint(", fn)
        self.assertIn("webpush.valid_keys(", fn)
        self.assertNotRegex(fn, r'body\.get\("user', "the account never comes from the body")

    def test_the_table_is_service_role_only(self):
        sql = read("db", "0075_web_push.sql")
        self.assertIn("enable row level security", sql)
        self.assertIn("revoke all on public.web_push_subs from public, anon, authenticated;", sql)
        for fn in re.findall(r"create or replace function public\.(web_push_\w+)", sql):
            self.assertRegex(sql, rf"grant execute on function public\.{fn}\([^)]*\) to service_role;")
            self.assertRegex(sql, rf"revoke all on function public\.{fn}\([^)]*\) from public, anon, authenticated;")


if __name__ == "__main__":
    unittest.main()
