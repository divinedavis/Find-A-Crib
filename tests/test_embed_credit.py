"""The /embed/ snippet's static credit line, and why every widget link is nofollowed.

Written 2026-11-11, at T016's (embeddable_building_lookup_widget) second
revisit. The technique's hypothesis is that "every embed turns into a
permanent, high-relevance backlink ... that moves the domain-authority
needle". The 2026-10-12 revisit found the backlink existed only in
JS-injected DOM and named the fix: put a real <a> in the host page's own
markup. Shipping that followed would have walked into the one thing Google
has said about this pattern for ten years — its spam policies name
"keyword-rich, hidden, or low-quality links embedded in widgets that are
distributed across various sites" as link spam and exempt links qualified
with rel="nofollow" or rel="sponsored"; the 2016 Search Central reminder
asks for nofollow on widget links; and in 2017 Google said it recognises a
widget across sites and nofollows those links automatically.

So the credit ships, and it ships nofollowed with the brand name as its
anchor text. These tests pin the four properties that make that defensible,
because each one is easy to undo by accident in a later "conversion" edit:

  1. the credit is in the HTML of the snippet, not only in rendered DOM;
  2. every link the widget puts on a third-party page carries nofollow;
  3. the anchor text is the brand name, not a keyword phrase;
  4. the live demo on /embed/ is the same thing the page tells people to paste.

Verified in a real browser on the day it shipped (Chromium via Playwright,
run by hand, not from this file): with a shadow root the credit stays in the
host's markup and is not drawn, without attachShadow it is cleared so the
credit is not shown twice, and with the script blocked a reader sees the
credit sentence instead of an empty box.
"""
from __future__ import annotations

import html
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "web" / "embed" / "index.html").read_text()
WIDGET = (ROOT / "web" / "embed" / "widget.js").read_text()

# The <pre><code> block the page tells people to paste.
SNIPPET = re.search(r"<pre><code>(.*?)</code></pre>", PAGE, re.S)
# The live demo's mount element.
DEMO = re.search(r'<div class="demo">\s*(<div id="findacrib-check">.*?</div>)\s*</div>',
                 PAGE, re.S)


def _norm(s: str) -> str:
    """Compare markup by content, not by indentation or entity spelling."""
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


class SnippetCarriesTheCredit(unittest.TestCase):
    def test_the_page_still_documents_a_snippet(self):
        self.assertIsNotNone(SNIPPET, "no <pre><code> paste block left on /embed/")

    def test_the_credit_anchor_is_in_the_snippet_itself(self):
        """Not in widget.js output — in the HTML an embedder pastes.

        This is the whole point of the change: a link that only exists after a
        host site executes our script is a weaker artifact than one in the
        host's own markup, and it is nothing at all when the script is blocked.
        """
        snippet = _norm(SNIPPET.group(1))
        self.assertIn("findacrib-check", snippet)
        self.assertRegex(
            snippet,
            r'<a href="https://findacrib\.com/" rel="nofollow">Find A Crib</a>',
            "the pasted snippet must contain a real nofollowed anchor",
        )

    def test_the_credit_sits_inside_the_mount_element(self):
        """Inside, so the shadow root hides it once the widget renders.

        Outside the mount div it would be drawn twice on every embed — the
        static line and the widget's own footer credit.
        """
        snippet = _norm(SNIPPET.group(1))
        mount = re.search(r'<div id="findacrib-check">(.*?)</div>', snippet, re.S)
        self.assertIsNotNone(mount, "mount div is self-closing again: credit moved out")
        self.assertIn("Find A Crib", mount.group(1))

    def test_the_anchor_text_is_the_brand_name_and_nothing_else(self):
        """Google's policy names KEYWORD-RICH widget links. Ours is a name.

        The descriptive words ("rent-stabilization lookup", the data sources)
        belong outside the <a>. If a later edit pulls them in to chase anchor
        text, this fails.
        """
        for anchor in re.findall(r"<a [^>]*>(.*?)</a>", _norm(SNIPPET.group(1)), re.S):
            self.assertEqual("Find A Crib", anchor.strip())


class EveryWidgetLinkIsNofollowed(unittest.TestCase):
    def test_widget_js_injects_no_followed_link(self):
        """Each el("a", {...}) in widget.js must declare a rel containing nofollow.

        There are two: the footer credit and the per-result "See it on the map"
        link. Both land on third-party pages, so both are widget links.
        """
        anchors = re.findall(r'el\("a",\s*\{(.*?)\}', WIDGET, re.S)
        self.assertGreaterEqual(len(anchors), 2, "widget.js stopped building anchors")
        for attrs in anchors:
            self.assertIn("rel:", attrs, f"anchor with no rel at all: {attrs.strip()}")
            rel = re.search(r'rel:\s*"([^"]*)"', attrs)
            self.assertIsNotNone(rel, f"rel is not a literal string: {attrs.strip()}")
            self.assertIn("nofollow", rel.group(1).split(),
                          f"followed widget link: rel={rel.group(1)!r}")

    def test_target_blank_links_keep_noopener(self):
        """Adding nofollow must not have displaced noopener on target=_blank."""
        for attrs in re.findall(r'el\("a",\s*\{(.*?)\}', WIDGET, re.S):
            if "_blank" in attrs:
                rel = re.search(r'rel:\s*"([^"]*)"', attrs).group(1).split()
                self.assertIn("noopener", rel)

    def test_the_no_shadow_path_clears_the_static_credit(self):
        """Without attachShadow nothing hides the light DOM, so mount() must.

        Otherwise an old browser shows the credit line AND the widget's footer
        credit, which looks like a bug and reads like double billing.
        """
        self.assertRegex(
            WIDGET,
            r"if \(!shadow\) \{\s*while \(host\.firstChild\)",
            "mount() no longer clears the host's children on the no-shadow path",
        )


class ThePageAgreesWithItself(unittest.TestCase):
    def test_the_live_demo_is_the_documented_snippet(self):
        """A demo that drifts from the paste block teaches the wrong thing."""
        self.assertIsNotNone(DEMO, "the live demo's mount element moved or went away")
        demo = _norm(DEMO.group(1))
        # The paste block is escaped source, so its own entities survive one
        # unescape ("&amp;mdash;" -> "&mdash;"); the demo's render on the first.
        # Unescape the snippet twice so the two are compared as rendered text.
        snippet_mount = re.search(r'<div id="findacrib-check">.*?</div>',
                                  _norm(html.unescape(SNIPPET.group(1))), re.S)
        self.assertIsNotNone(snippet_mount)
        self.assertEqual(snippet_mount.group(0), demo)

    def test_the_page_says_why_the_link_is_nofollowed(self):
        """An embedder who notices the rel deserves the reason on the page.

        Silently shipping a rel they did not ask for is the kind of small
        dishonesty this site cannot afford.
        """
        self.assertIn("nofollow", PAGE)
        self.assertRegex(PAGE, r"(?i)spam polic")

    def test_the_building_level_caveat_survived_the_edit(self):
        """Non-negotiable, and it sits next to copy that got rewritten today."""
        self.assertIn("Registration is at the", PAGE)
        self.assertIn("Registration is at the building level", WIDGET)


if __name__ == "__main__":
    unittest.main()
