#!/usr/bin/env python3
"""db/0071 (2026-10-30): dashboard_metrics' ev_all/ios_ev and
dashboard_adtiles' r keep only the props keys the rest of each function
reads, instead of the whole jsonb. That took all-time calls from 5.3 s and
13.1 s to 3.8 s and 5.1 s with identical output — and it holds only while
no later edit reads a key the slim CTE dropped. A dropped key reads as NULL,
silently zeroing a tile, so these tests fail first."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATION = os.path.join(ROOT, "db", "0071_dashboard_slim_ctes.sql")


def _function(sql, name):
    start = sql.index(f"FUNCTION public.{name}(")
    end = sql.index("$function$", sql.index("$function$", start) + 1)
    return sql[start:end]


class DashboardSlimCtes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(MIGRATION) as f:
            cls.sql = f.read()
        cls.metrics = _function(cls.sql, "dashboard_metrics")
        cls.adtiles = _function(cls.sql, "dashboard_adtiles")

    def test_metrics_reads_only_kept_keys(self):
        # ev_all keeps platform/kind/via, ios_ev platform/build; 'build' is
        # only ever read in WHERE clauses on public.events itself.
        keys = set(re.findall(r"props->>'(\w+)'", self.metrics))
        self.assertLessEqual(keys, {"platform", "kind", "via", "build"},
                             "a new props key must be added to ev_all/ios_ev too")

    def test_metrics_ctes_are_slim(self):
        self.assertNotIn("select e.* from public.events e", self.metrics)
        self.assertNotIn("select * from public.events", self.metrics)
        self.assertIn("'via', props->'via') as props", self.metrics)
        self.assertIn("'build', e.props->'build') as props", self.metrics)

    def test_adtiles_tile_rows_use_columns(self):
        r = self.adtiles[self.adtiles.index("with r as ("):self.adtiles.index("edges as (")]
        self.assertIn("case when event in ('featured_click', 'hc_click') then props end as props", r)
        for col in ("p_kind", "p_agent", "p_platform", "p_addr"):
            self.assertIn(col, r)
        # Everything after r that reads props reads click rows (which keep
        # props) or public.events directly — never a tile key off r/t.
        rest = self.adtiles[self.adtiles.index("edges as ("):]
        for key in ("kind", "agent", "addr"):
            self.assertNotIn(f"props->>'{key}'", rest)

    def test_composite_index_replaces_event_index(self):
        self.assertIn("on public.events (event, created_at desc)", self.sql)
        self.assertIn("drop index concurrently if exists public.events_event_idx", self.sql)


if __name__ == "__main__":
    unittest.main()
