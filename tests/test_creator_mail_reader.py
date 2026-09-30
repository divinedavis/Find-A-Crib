"""find_rate() on real and typical creator replies. Run: python3 -m pytest tests/test_creator_mail_reader.py"""
import os, sys, tempfile

os.environ.setdefault("CREATOR_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from creator_mail_reader import find_rate  # noqa: E402

PITCH = """

On Wed, Sep 30, 2026 at 8:05 AM Marracat <hello@marracat.com> wrote:

> If you're interested, reply with your rate and we'll take it from there.
> Budget $75.
"""


def test_typical_reply():
    body = ("Hi!\n\nThanks for reaching out, I'm interested.\n\n"
            "My rate for the requested TikTok video is $400 CAD, which covers the\n"
            "organic video deliverable outlined in the brief.\n\n"
            "I'd be happy to discuss a separate usage fee if the content will be reused.\n\nBest,\nA" + PITCH)
    rate, quote = find_rate(body)
    assert rate == "$400 CAD"
    assert quote.startswith("My rate for the requested TikTok video")


def test_formats():
    assert find_rate("I charge $1,200 per video.")[0] == "$1,200"
    assert find_rate("My rate is 1.5k USD for one TikTok.")[0] == "$1,500"
    assert find_rate("Rate: £300 per post")[0] == "£300"
    assert find_rate("Sounds great, it would be 250 dollars")[0] == "$250"
    assert find_rate("My fee is CA$500.")[0] == "$500 CAD"


def test_first_amount_in_rate_sentence_wins():
    assert find_rate("Loved the brief! My rate is $350 for one video, or $600 for two.")[0] == "$350"


def test_quoted_pitch_is_ignored():
    assert find_rate("Yes I'm interested, let's talk Thursday." + PITCH) == (None, None)


def test_no_money():
    assert find_rate("Can you send me more info about the app?") == (None, None)
    assert find_rate("I have 2 kids and 3 videos planned this week.") == (None, None)
