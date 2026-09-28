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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
