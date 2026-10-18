"""error_report.js_errors — stackless ad-stack rejections are browser noise."""
import error_report as E


def row(msg, kind="promise", at=""):
    return {"event": "js_error", "props": {"msg": msg, "kind": kind, "at": at},
            "visitor_id": "v1", "path": "/", "created_at": "2026-10-05T01:26:45Z"}


def test_stackless_timeout_and_unavailable_are_noise():
    js = E.js_errors([row("operation timed out"), row("UnavailableError"),
                      row("Cannot destructure property 'data' from null or undefined value")])
    assert all(v["noise"] for v in js.values())


def test_the_same_words_with_our_stack_are_not():
    js = E.js_errors([row("operation timed out", at="https://findacrib.com/:5123")])
    assert not any(v["noise"] for v in js.values())


def test_a_safari_extension_error_is_noise():
    js = E.js_errors([row("_0x43b06e is not an Object. (evaluating '_0x1617de in _0x43b06e')",
                          at="IhDtT@webkit-masked-url://hidden/:14816:55")])
    assert all(v["noise"] for v in js.values())


def test_a_real_error_is_not_noise():
    js = E.js_errors([row("TypeError: undefined is not an object (evaluating 'b.price')", kind="error",
                          at="https://findacrib.com/:4410")])
    assert not any(v["noise"] for v in js.values())


def signin(text, result="error"):
    return {"event": "signin", "visitor_id": "v1", "created_at": "2026-10-17T01:57:43Z",
            "props": {"platform": "ios", "provider": "email", "result": result, "text": text}}


def test_a_wrong_password_is_not_an_app_failure():
    assert not E.app_failures([signin("Invalid login credentials")])


def test_other_signin_errors_still_count():
    assert "Sign-in failed (email)" in E.app_failures([signin("The network connection was lost.")])
