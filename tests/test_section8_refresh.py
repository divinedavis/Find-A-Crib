"""growth/section8_refresh.py: rebuilds /section8/ without the growth ledger."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from growth import ledger, section8_refresh, techniques  # noqa: E402


class Section8RefreshTests(unittest.TestCase):
    def test_writes_docroot_and_never_the_ledger(self):
        with tempfile.TemporaryDirectory() as docroot:
            def fake(ctx):
                ctx.write_page("section8/index.html", "<p>hub</p>")
                ctx.write_page("section8/brooklyn/index.html", "<p>bk</p>")
                return {"ok": True, "pages": 2}
            with mock.patch.object(techniques, "t_fresh_section8", fake), \
                 mock.patch.object(ledger, "set_state") as set_state, \
                 mock.patch.dict(os.environ, {"GROWTH_DOCROOT": docroot}):
                self.assertEqual(section8_refresh.main(), 0)
            set_state.assert_not_called()
            with open(os.path.join(docroot, "section8/brooklyn/index.html")) as f:
                self.assertEqual(f.read(), "<p>bk</p>")

    def test_refusal_leaves_docroot_alone(self):
        with tempfile.TemporaryDirectory() as docroot:
            with mock.patch.object(techniques, "t_fresh_section8",
                                   lambda ctx: {"ok": False, "detail": "thin"}), \
                 mock.patch.dict(os.environ, {"GROWTH_DOCROOT": docroot}):
                self.assertEqual(section8_refresh.main(), 1)
            self.assertFalse(os.path.exists(os.path.join(docroot, "section8")))

    def test_cron_runs_it_after_the_feed(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "deploy/cron-rentmap-scrape")) as f:
            lines = [l for l in f if l.strip() and not l.startswith("#")]
        feed = next(l for l in lines if "scrape_affordablehousing.py" in l).split()
        page = next(l for l in lines if "section8_refresh.py" in l).split()
        self.assertGreater((int(page[1]), int(page[0])), (int(feed[1]), int(feed[0])))


if __name__ == "__main__":
    unittest.main()
