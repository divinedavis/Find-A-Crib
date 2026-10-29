"""Guide pages lead with a liftable answer, a date and a matching FAQ
(2026-10-29, owner: get Gemini, Claude and ChatGPT to cite Find A Crib)."""
import json
import re

import build_seo as B

FIND = "how-to-find-a-rent-stabilized-apartment"
CHECK = "is-my-apartment-rent-stabilized"


def render(slug):
    return B.guide_page(next(g for g in B.GUIDES if g["slug"] == slug))[1]


def ld_blocks(doc):
    return [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', doc, re.S)]


def test_both_guides_open_with_an_answer_inside_the_extractable_window():
    for slug in (FIND, CHECK):
        doc = render(slug)
        answer = re.search(r"<div class='answer'><p>(.*?)</p>", doc).group(1)
        assert B.ANSWER_MIN_WORDS <= len(answer.split()) <= B.ANSWER_MAX_WORDS, slug
        # The answer comes before the guide's own text.
        assert doc.index("class='answer'") < doc.index("class='guide-body'"), slug


def test_the_building_count_is_filled_in_and_never_left_as_a_token():
    for slug in (FIND, CHECK):
        doc = render(slug)
        assert "{buildings}" not in doc
        n = B.guide_stats().get("buildings")
        if n:
            assert f"{n:,}" in doc


def test_faq_json_ld_matches_the_visible_questions():
    for slug in (FIND, CHECK):
        doc = render(slug)
        faq = [b for b in ld_blocks(doc)[0] if b.get("@type") == "FAQPage"]
        assert len(faq) == 1, slug
        for q in faq[0]["mainEntity"]:
            assert B.esc(q["name"]) in doc, q["name"]


def test_the_date_line_and_date_modified_agree():
    doc = render(FIND)
    article = next(b for b in ld_blocks(doc)[0] if b.get("@type") == "Article")
    assert article["dateModified"] == "2026-10-29"
    assert "Updated October 29, 2026" in doc


def test_the_check_guide_has_an_address_box_that_feeds_the_maps_search():
    doc = render(CHECK)
    form = re.search(r"<form action='/' method='get'.*?</form>", doc, re.S).group(0)
    assert "name='q'" in form
    assert "<form" not in render(FIND)


def test_the_find_guide_names_where_vacancies_are_listed_with_a_source():
    doc = render(FIND)
    for needle in ("find-affordable-housing-re-rentals.page", "housingconnect.nyc.gov", "0.98%",
                   "2023-nychvs-selected-initial-findings.pdf", "href='/alerts/'"):
        assert needle in doc, needle


def test_a_guide_without_the_new_keys_renders_as_before():
    g = next(g for g in B.GUIDES if g["slug"] == "deed-theft-nyc")
    doc = B.guide_page(g)[1]
    assert "class='answer'" not in doc and "FAQPage" not in doc and "Updated " not in doc
