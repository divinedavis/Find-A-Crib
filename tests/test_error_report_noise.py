"""error_report.js_errors — stackless ad-stack rejections are browser noise."""
import error_report as E


def row(msg, kind="promise", at="", name=None):
    return {"event": "js_error", "props": {"msg": msg, "kind": kind, "at": at, **({"name": name} if name else {})},
            "visitor_id": "v1", "path": "/", "created_at": "2026-10-05T01:26:45Z"}


def test_stackless_timeout_and_unavailable_are_noise():
    js = E.js_errors([row("operation timed out"), row("UnavailableError"),
                      row("Cannot destructure property 'data' from null or undefined value")])
    assert all(v["noise"] for v in js.values())


def test_the_same_words_with_our_stack_are_not():
    js = E.js_errors([row("operation timed out", at="https://findacrib.com/:5123")])
    assert not any(v["noise"] for v in js.values())


def test_a_rejection_with_no_reason_is_noise():
    js = E.js_errors([row("", name="undefined")])
    assert all(v["noise"] for v in js.values())


def test_an_empty_error_with_a_name_or_our_stack_is_not():
    js = E.js_errors([row("", name="TypeError"), row("", name="undefined", at="https://findacrib.com/:812")])
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


def test_cancel_on_googles_consent_page_is_not_an_app_failure():
    r = signin("Error in URL with unspecified error_description.")
    r["props"]["provider"] = "google"
    assert not E.app_failures([r])


APPLE_1000 = "The operation couldn’t be completed. (com.apple.AuthenticationServices.AuthorizationError error 1000.)"


def apple(visitor):
    r = signin(APPLE_1000)
    r["props"]["provider"], r["visitor_id"] = "apple", visitor
    return r


def test_one_phone_without_sign_in_with_apple_is_not_an_app_failure():
    assert not E.app_failures([apple("v1"), apple("v1"), apple("v1")])


def test_two_people_with_apple_1000_still_count():
    out = E.app_failures([apple("v1"), apple("v2")])
    assert out["Sign-in failed (apple)"]["n"] == 2


def test_a_third_party_file_is_noise():
    # 2026-10-27: someone else's rxEngine.wasm; the site ships no WebAssembly.
    wasm = {"event": "js_error", "props": {"msg": "Uncaught RuntimeError: memory access out of bounds",
                                           "src": "-0-production-endpoint-v1/rxEngine.wasm?0ffb634e09e360335251"},
            "visitor_id": "v1", "path": "/", "created_at": "2026-10-28T00:13:16Z"}
    other = {"event": "js_error", "props": {"msg": "TypeError: x is undefined", "src": "https://ads.example/a.js",
                                            "host": "ads.example"},
             "visitor_id": "v1", "path": "/", "created_at": "2026-10-28T00:13:16Z"}
    ours = {"event": "js_error", "props": {"msg": "TypeError: x is undefined", "src": "https://findacrib.com/",
                                           "host": "findacrib.com"},
            "visitor_id": "v1", "path": "/", "created_at": "2026-10-28T00:13:16Z"}
    assert all(v["noise"] for v in E.js_errors([wasm, other]).values())
    assert not any(v["noise"] for v in E.js_errors([ours]).values())
