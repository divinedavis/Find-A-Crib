"""error_report.js_errors — stackless ad-stack rejections are browser noise."""
import error_report as E


def row(msg, kind="promise", at=""):
    return {"event": "js_error", "props": {"msg": msg, "kind": kind, "at": at},
            "visitor_id": "v1", "path": "/", "created_at": "2026-10-05T01:26:45Z"}


def test_stackless_timeout_and_unavailable_are_noise():
    js = E.js_errors([row("operation timed out"), row("UnavailableError")])
    assert all(v["noise"] for v in js.values())


def test_the_same_words_with_our_stack_are_not():
    js = E.js_errors([row("operation timed out", at="https://findacrib.com/:5123")])
    assert not any(v["noise"] for v in js.values())


def test_a_real_error_is_not_noise():
    js = E.js_errors([row("TypeError: undefined is not an object (evaluating 'b.price')", kind="error",
                          at="https://findacrib.com/:4410")])
    assert not any(v["noise"] for v in js.values())
