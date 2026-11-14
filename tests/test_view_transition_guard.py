"""index.html opts into cross-document view transitions; Safari rejects the
transition's promises with AbortError whenever it skips one (back/forward cache,
hidden tab), which reached the error digest as an unhandled rejection on
2026-11-13. A head script must catch them before the first frame, and the
telemetry must not report any it misses."""
import re
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text()
HEAD = HTML.split("</head>", 1)[0]


def test_view_transitions_are_still_opted_in():
    # If the opt-in goes, this whole guard (and test) can go with it.
    assert "@view-transition" in HTML


def test_head_catches_the_transition_promises_for_both_events():
    script = next(s for s in re.findall(r"<script>(.*?)</script>", HEAD, re.S) if "viewTransition" in s)
    for event in ("pagereveal", "pageswap"):
        assert f"addEventListener('{event}'" in script
    for promise in ("ready", "finished", "updateCallbackDone"):
        assert f"v.{promise}" in script
    assert ".catch(" in script


def test_the_guard_runs_before_any_render_blocking_style():
    # pagereveal fires before the first frame: the listener has to be in place
    # before the stylesheet that turns transitions on.
    assert HTML.index("addEventListener('pagereveal'") < HTML.index("@view-transition")


def test_telemetry_skips_a_skipped_transition():
    i = HTML.index("addEventListener('unhandledrejection'")
    body = HTML[i:i + 1500]
    assert "AbortError" in body and "view transition" in body
