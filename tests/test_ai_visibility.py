"""growth/ai_visibility.py, the monthly "do chatbots send people here" check."""
import datetime
from unittest import mock

from growth import ai_visibility as A

TODAY = datetime.date(2026, 11, 1)


def resp(text, urls, usage=None):
    return {"content": [
        {"type": "server_tool_use", "name": "web_search"},
        {"type": "web_search_tool_result", "content": [{"url": "https://read-not-cited.example/"}]},
        {"type": "text", "text": text, "citations": [{"url": u} for u in urls]}],
        "usage": usage or {"input_tokens": 20000, "output_tokens": 800}}


def test_only_cited_urls_count_and_www_is_folded():
    text, hosts = A.read_answer(resp("See StreetEasy.", ["https://www.streeteasy.com/blog/x",
                                                         "https://streeteasy.com/y"]))
    assert hosts == ["streeteasy.com"]
    assert "read-not-cited.example" not in hosts


def test_a_findacrib_citation_and_a_name_mention_are_told_apart():
    with mock.patch.object(A.scout, "record_spend", lambda *a: 0):
        r = A.claude_reading("k", call=lambda body: resp(
            "Try Find A Crib, a free map.", ["https://findacrib.com/guide/x/", "https://nyc.gov/"]))
    assert r["asked"] == len(A.QUESTIONS)
    assert r["cited"] == r["named"] == len(A.QUESTIONS)
    assert r["cost"] > 0
    with mock.patch.object(A.scout, "record_spend", lambda *a: 0):
        r = A.claude_reading("k", call=lambda body: resp("Use the RGB list.", ["https://rentguidelinesboard.cityofnewyork.us/"]))
    assert r["cited"] == r["named"] == 0


def test_a_lookalike_domain_is_not_a_citation():
    with mock.patch.object(A.scout, "record_spend", lambda *a: 0):
        r = A.claude_reading("k", call=lambda body: resp("x", ["https://notfindacrib.com/"]))
    assert r["cited"] == 0


def test_one_failed_question_keeps_the_rest():
    calls = []

    def call(body):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("timed out")
        return resp("x", ["https://findacrib.com/"])
    with mock.patch.object(A.scout, "record_spend", lambda *a: 0):
        r = A.claude_reading("k", call=call)
    assert r["cited"] == len(A.QUESTIONS) - 1
    assert "timed out" in r["answers"][1]["error"]


def test_the_question_uses_web_search_and_the_engines_model():
    seen = {}
    with mock.patch.object(A.scout, "record_spend", lambda *a: 0):
        A.ask_claude("k", "q?", call=lambda body: seen.update(body) or resp("x", []))
    assert seen["model"] == A.scout.MODEL
    assert seen["tools"][0]["type"].startswith("web_search")


def test_referrals_count_unique_visitors_per_source():
    def fetch(q):
        if "chatgpt" in q:
            return [{"visitor_id": "a"}, {"visitor_id": "a"}, {"visitor_id": "b"}, {"visitor_id": None}]
        return []
    r = A.referral_reading(TODAY, fetch=fetch)
    assert r["chatgpt"] == 2 and r["perplexity"] == 0
    assert set(r) == set(A.AI_SOURCES)


def test_gemini_reading_weights_position_by_impressions():
    rows = [{"keys": ["rent stabilized apartments nyc"], "impressions": 30, "clicks": 1, "position": 10.0},
            {"keys": ["is my building rent stabilized"], "impressions": 10, "clicks": 0, "position": 30.0},
            {"keys": ["findacrib"], "impressions": 500, "clicks": 400, "position": 1.0}]
    import seo_search_console as sc
    with mock.patch.object(sc, "load_key", lambda: {}), mock.patch.object(sc, "access_token", lambda k: "t"):
        g = A.gemini_reading(TODAY, query=lambda *a, **k: rows, inspect=lambda t, u: "URL is unknown to Google")
    assert g["impressions"] == 40 and g["clicks"] == 1 and g["position"] == 15.0
    assert set(g["pages"]) == set(A.PAGES)


def test_summary_reports_change_against_last_month():
    rec = {"claude": {"asked": 5, "cited": 2, "named": 3, "answers": [{"hosts": ["nyc.gov", "reddit.com"]}]},
           "gemini": {"impressions": 40, "clicks": 1, "pages": {"a": "Submitted and indexed", "b": "URL is unknown to Google"}},
           "referrals": {"chatgpt": 30, "perplexity": 1, "claude": 0, "gemini": 0, "copilot": 2}}
    prev = {"claude": {"cited": 0}, "gemini": {"impressions": 0}, "referrals": {"chatgpt": 25}}
    s = " ".join(A.summary_lines(rec, prev))
    assert "2 of 5 answers (+2 vs last month)" in s
    assert "40 impressions" in s and "(+40 vs last month)" in s
    assert "indexed 1 of 2" in s
    assert "ChatGPT sent 30 visitors in 30 days (+5 vs last month)" in s


def test_a_missing_reading_says_so_instead_of_zero():
    s = " ".join(A.summary_lines({"claude": {"error": "no Anthropic key"}, "gemini": {"error": "x"},
                                  "referrals": {"error": "y"}}))
    assert "Claude: not measured" in s and "Google: not measured" in s and "AI referrals: not measured" in s
