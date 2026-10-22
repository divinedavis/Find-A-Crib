"""error_report.crashes: a sub-second shadow page is not a death when its
visitor kept using the site, and still is when they did not."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import error_report as er  # noqa: E402

NOW = "2026-09-28T15:00:12+00:00"


def trace(vid, steps, booted="2026-09-28T13:49:51.410Z"):
    return {"event": "crash_trace", "visitor_id": vid, "created_at": NOW,
            "props": {"booted": booted, "ua": "iPhone", "steps": [[i, s] for i, s in enumerate(steps)]}}


SHADOW = ["boot", "grid:done", "map-resize 678", "auth INITIAL_SESSION", "adoptHome"]


def test_shadow_page_with_active_visitor_is_dropped():
    out = er.crashes([trace("v1", SHADOW)], key="k", kept_going=lambda *a: True)
    assert not out


def test_shadow_page_with_no_later_activity_still_reports():
    out = er.crashes([trace("v1", SHADOW)], key="k", kept_going=lambda *a: False)
    assert out["adoptHome"]["n"] == 1


def test_unknown_activity_keeps_the_trace():
    out = er.crashes([trace("v1", SHADOW)], key="k", kept_going=lambda *a: None)
    assert out["adoptHome"]["n"] == 1


def test_page_that_lived_past_a_tick_is_never_looked_up():
    calls = []
    steps = ["boot", "tick", "tick", "grid:build 200", "la:mount 1/0"]
    out = er.crashes([trace("v1", steps)], key="k", kept_going=lambda *a: calls.append(a) or True)
    assert out["la:mount 1/0"]["n"] == 1 and not calls


def test_a_page_born_hidden_and_never_shown_is_not_a_death():
    # 2026-10-20 digest: "adoptHome" / "vv-resize ad0" 0.4 s after boot, no tick.
    hidden = ["boot hidden", "grid:done", "auth INITIAL_SESSION", "adoptHome"]
    assert not er.crashes([trace("v1", hidden)], key="k", kept_going=lambda *a: False)


def test_a_page_born_hidden_that_was_then_shown_still_counts():
    shown = ["boot hidden", "vis visible", "tick", "grid:build 200", "la:mount 1/0"]
    assert er.crashes([trace("v1", shown)], key="k", kept_going=lambda *a: False)["la:mount 1/0"]["n"] == 1


def test_a_page_that_ended_hidden_is_not_a_death_whatever_ran_there():
    # 2026-10-22 digest: feeds refreshed in a hidden Chrome tab, then a photo timed out.
    steps = ["boot", "tick", "openDetail", "la:mount 1/0", "vis hidden", "grid:feeds",
             "grid:build 200", "grid:done", "tick", "la:fail:timeout 1"]
    assert not er.crashes([trace("v1", steps)], key="k", kept_going=lambda *a: False)


def test_hidden_then_shown_again_still_counts():
    steps = ["boot", "tick", "vis hidden", "vis visible", "tick", "la:mount 2/1"]
    assert er.crashes([trace("v1", steps)], key="k", kept_going=lambda *a: False)["la:mount 2/1"]["n"] == 1


def test_one_lone_boot_is_not_news_but_a_repeat_is():
    assert not er.crashes([trace("v1", ["boot"])], key="k", kept_going=lambda *a: False)
    out = er.crashes([trace("v1", ["boot"]), trace("v1", ["boot"]), trace("v2", ["boot"])],
                     key="k", kept_going=lambda *a: False)
    assert out["boot"]["n"] == 2 and out["boot"]["people"] == {"v1"}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)


def test_trace_without_boot_stamp_is_history():
    # Pages from before 2026-09-24 carry no "booted"; their report is old news.
    out = er.crashes([trace("v1", ["boot", "grid:done"], booted=None)], key="k", kept_going=lambda *a: False)
    assert not out


def test_plain_text_hides_browser_noise():
    """2026-10-16: the text part listed 62 ad-script "Load failed" rows that
    the HTML part correctly folded into one noise line."""
    import error_report as R
    from collections import Counter
    js = {"Load failed": {"n": 62, "people": {"a"}, "paths": Counter(), "last": "", "noise": True},
          "Real bug": {"n": 2, "people": {"b"}, "paths": Counter(), "last": "", "noise": False}}
    out = R.build("last 24 hours", js, {}, {}, Counter(), Counter(), {}, set())
    text = next(p for p in (out if isinstance(out, (tuple, list)) else [out]) if isinstance(p, str) and "Find A Crib errors —" in p)
    assert "Real bug" in text
    assert "Load failed" not in text
    assert "62 browser-noise" in text
