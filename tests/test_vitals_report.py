"""vitals_report.py: real-visit speed from the /vitals log (2026-11-10)."""
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

import vitals_report as vr

ROOT = Path(__file__).resolve().parent.parent
LOG = """2026-11-01T10:00:00+00:00 p=nyc&lcp=1500-2500&fcp=0-1000&r=1
2026-11-10T10:00:00+00:00 p=nyc&lcp=1500-2500&fcp=0-1000&ttfb=0-200&r=1
2026-11-10T10:01:00+00:00 p=nyc&lcp=2500-4000&cls=0-0.1&i=1
2026-11-10T10:02:00+00:00 p=la&lcp=10000+&inp=500-1000
not a line
2026-11-10T10:03:00+00:00 p=nyc&lcp=nonsense
""".splitlines()


class Report(unittest.TestCase):
    def test_shares_good_and_poor_per_measure_within_the_window(self):
        r = vr.report(vr.parse(LOG, datetime(2026, 11, 5, tzinfo=timezone.utc)))
        self.assertEqual(r["visits"], 4)
        self.assertEqual((r["repeat"], r["installed"]), (1, 1))
        self.assertEqual(r["maps"], {"nyc": 3, "la": 1})
        self.assertEqual(r["measures"]["lcp"], {"visits": 3, "good_pct": 33, "poor_pct": 33,
                                                "ranges": {"1500-2500": 1, "2500-4000": 1, "10000+": 1}})
        self.assertEqual(r["measures"]["inp"]["poor_pct"], 100)
        self.assertNotIn("ttfb", vr.report(vr.parse(LOG, datetime(2026, 11, 5, tzinfo=timezone.utc)), "la")["measures"])

    def test_every_good_line_is_a_range_edge_the_page_sends(self):
        js = (ROOT / "web" / "static" / "platform" / "vitals.js").read_text()
        edges = {k: [float(x) for x in v.split(",")] for k, v in re.findall(r"(\w+): \[([\d, ]+)\]", js)}
        for k in ("ttfb", "fcp", "lcp", "inp"):
            for line in vr.LINES[k]:
                self.assertIn(line, edges[k], k)

    def test_the_log_takes_only_what_the_page_sends(self):
        conf = (ROOT / "deploy" / "nginx" / "conf.d" / "log_format_site.conf").read_text()
        allowed = re.search(r'"~\^\[(.+?)\]\{1,200\}\$"', conf).group(1)
        js = (ROOT / "web" / "static" / "platform" / "vitals.js").read_text()
        self.assertIn("log_format fac_vitals '$time_iso8601 $args';", conf, "no address, browser or cookie in the log")
        for sample in ("p=nyc&lcp=1500-2500&fcp=0-1000&ttfb=0-200&inp=0-100&cls=0-0.1&c=4g&i=1&r=1", "p=westchester&lcp=10000+"):
            self.assertRegex(sample, f"^[{allowed}]{{1,200}}$")
        self.assertIn('"/vitals?"', js)


if __name__ == "__main__":
    unittest.main()
