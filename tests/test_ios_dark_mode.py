"""Dark mode in the iPhone app stays whole (owner, 2026-11-22).

The app follows the phone's Light / Dark setting. That works only while every
colour comes from Theme.swift's light/dark pairs, and it breaks one view at a
time: a new card drawn on Color.white is a white slab on a dark screen, and
teal text taken from the fill token is unreadable on a dark card. Nothing
fails to compile when that happens, so these tests read the Swift sources.

What they hold:
  1. nothing pins the app or its navigation bar to light: the one scheme is
     set at the root from Profile › Appearance (Light, Dark, or follow the
     phone), with --dark / --light at launch for tests and screenshots;
  2. no view paints a background or fill with plain white (SE.surface is the
     colour a card is drawn on), with a short, explained list of exceptions;
  3. text, icons and outlines use the ink tokens (royalInk, goodInk, warnInk,
     badInk), fills use the fill tokens; see the note at the top of `enum SE`;
  4. every ink clears 4.5:1 on the dark card and the dark canvas, and white
     text clears 4.5:1 on every dark fill, by the WCAG formula Apple's
     accessibility audit uses;
  5. light mode is exactly what it was: the light half of every pair is the
     hex the app shipped with before dark mode.

The UI tests run the real thing: AccessibilityAuditDarkTests (Apple's audit on
every main screen in dark) and DarkModeTests (the app switches while running
on iPhone; two more screens are dark on iPhone and iPad).
"""
import glob
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "ios", "FindACrib")
THEME = os.path.join(APP, "Design", "Theme.swift")


def sources():
    for path in sorted(glob.glob(os.path.join(APP, "**", "*.swift"), recursive=True)):
        with open(path, encoding="utf-8") as f:
            yield os.path.relpath(path, APP), f.read()


def code_lines():
    """(file, line number, code) for every line, comments cut off."""
    for name, text in sources():
        for i, line in enumerate(text.split("\n"), 1):
            yield name, i, line.split("//")[0]


def pairs():
    with open(THEME, encoding="utf-8") as f:
        theme = f.read()
    return {m.group(1): (int(m.group(2), 16), int(m.group(3), 16))
            for m in re.finditer(r"static let (\w+)\s*= Color\(light: 0x([0-9A-Fa-f]{6}), dark: 0x([0-9A-Fa-f]{6})\)", theme)}


def luminance(rgb):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(rgb >> 16 & 255) + 0.7152 * lin(rgb >> 8 & 255) + 0.0722 * lin(rgb & 255)


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# The light values the app shipped with before dark mode (build 168).
SHIPPED_LIGHT = {
    "navy": 0x163C47, "navyDeep": 0x0F2B33, "royal": 0x2A7889, "royalDark": 0x255F6C,
    "green": 0x1E8E3E, "paleBlue": 0xD6ECF0, "paleBand": 0xE6F3F5, "ink": 0x1A1A1A,
    "ink2": 0x4A4A4A, "ink3": 0x595959, "line": 0xBDBDBD, "lineSoft": 0xE4E4E4,
    "canvas": 0xF2F2F7, "badge": 0xE8E8E8, "facts": 0x1F2937, "good": 0x1E7B34,
    "warn": 0xB25000, "bad": 0xB91C1C,
}
INKS = ("royalInk", "goodInk", "warnInk", "badInk", "navyInk", "ink", "ink2", "ink3", "plusInk", "mintInk")
FILLS = ("royal", "good", "warn", "bad")

# White that is meant to be white in both modes. Each entry is a file and the
# reason; a new one needs the same.
WHITE_ALLOWED = {
    "Design/Components.swift": "the knob of the switch",
    "Features/Profile/PaywallView.swift": "the price chip on the paywall hero's fixed gradient",
}


class ProfileAppearanceSetting(unittest.TestCase):
    """Profile › Appearance: Light, Dark, or the phone's setting (owner,
    2026-11-22). DarkModeTests.testProfileAppearancePicksLightDarkOrThePhone
    taps through it; these hold the wiring a simulator run cannot see."""

    def setUp(self):
        self.texts = dict(sources())
        self.src = self.texts["Services/Appearance.swift"]

    def test_three_choices_and_the_phone_is_the_default(self):
        self.assertIn("case system, light, dark", self.src)
        self.assertIn("?? .system", self.src, "with nothing stored the app follows the phone")

    def test_following_the_phone_means_no_scheme_at_all(self):
        """.system must hand SwiftUI nil, not today's appearance frozen in."""
        self.assertRegex(self.src, r"case \.system: return nil")
        self.assertRegex(self.src, r"case \.light: return \.light")
        self.assertRegex(self.src, r"case \.dark: return \.dark")

    def test_a_tests_flag_beats_the_pick(self):
        body = self.src[self.src.index("var scheme: ColorScheme?"):]
        self.assertLess(body.index("SE.forcedScheme"), body.index("switch choice"),
                        "--dark / --light are checked before the stored pick")

    def test_the_skyline_asks_the_same_place_as_the_colours(self):
        """SE.isDark decides day or night skyline. If it read only the phone,
        Dark picked on a light phone would draw a day skyline on a dark screen."""
        theme = self.texts["Design/Theme.swift"]
        body = theme[theme.index("static var isDark: Bool"):theme.index("static var isDark: Bool") + 400]
        self.assertIn("Appearance.shared.scheme", body)

    def test_profile_has_the_row(self):
        profile = self.texts["Features/Profile/ProfileView.swift"]
        self.assertIn('settingRow(String(localized: "Appearance"))', profile)
        self.assertIn('.accessibilityIdentifier("profile-appearance")', profile)
        self.assertIn("Appearance.shared.choose($0)", profile)
        # The row is read out as "Appearance, Dark", not a bare "Dark": bare,
        # "iPhone setting" was the same label as an item in the Language menu.
        self.assertIn('.accessibilityLabel(Text(verbatim: "\\(String(localized: "Appearance")), \\(Appearance.shared.choice.title)"))', profile)
        self.assertLess(profile.index('"profile-language"'), profile.index('"profile-appearance"'),
                        "it sits under Language")

    def test_the_words_are_translated(self):
        import json
        cat = json.load(open(os.path.join(ROOT, "ios", "Shared", "Localizable.xcstrings")))["strings"]
        for key in ("Appearance", "Light", "Dark", "iPhone setting"):
            self.assertIn(key, cat, f"{key!r} is in the string catalog")
            for lang in ("es", "ko", "zh-Hans", "zh-Hant"):
                unit = cat[key].get("localizations", {}).get(lang, {}).get("stringUnit", {})
                self.assertTrue(unit.get("value"), f"{key!r} has a {lang} translation")
                self.assertEqual(unit.get("state"), "translated", f"{key!r} in {lang} was reviewed, not machine output")


class NothingPinsTheAppToLight(unittest.TestCase):
    def test_no_view_forces_a_colour_scheme(self):
        hits = [f"{n}:{i}" for n, i, code in code_lines()
                if re.search(r"preferredColorScheme\(\s*\.(light|dark)\s*\)|toolbarColorScheme\(\s*\.(light|dark)", code)]
        self.assertEqual(hits, [], "these pin a screen or its bar to one appearance")

    def test_the_only_pin_is_the_appearance_setting(self):
        """One preferredColorScheme in the whole app, at the root, fed by
        Appearance: nil (follow the phone) unless someone picked Light or Dark
        in Profile, or a test launched with --dark / --light. Those flags
        exist for screenshots and for UI tests on iPad, whose simulator cannot
        be switched from a test."""
        texts = dict(sources())
        self.assertEqual(sum(t.count("preferredColorScheme(") for t in texts.values()), 1)
        self.assertIn(".preferredColorScheme(appearance.scheme)", texts["App/FindACribApp.swift"])
        self.assertIn("@State private var appearance = Appearance.shared", texts["App/FindACribApp.swift"])
        self.assertRegex(texts["Design/Theme.swift"],
                         r'static let forcedScheme: ColorScheme\? = CommandLine\.arguments\.contains\("--dark"\) \? \.dark\s*'
                         r': \(CommandLine\.arguments\.contains\("--light"\) \? \.light : nil\)')

    def test_the_plist_does_not_force_a_style(self):
        with open(os.path.join(ROOT, "ios", "project.yml"), encoding="utf-8") as f:
            self.assertNotIn("UIUserInterfaceStyle", f.read())


class CardsAreDrawnOnTheSurfaceColour(unittest.TestCase):
    def test_no_background_or_fill_is_plain_white(self):
        bad = []
        for name, i, code in code_lines():
            if name == "Design/Theme.swift" or name in WHITE_ALLOWED:
                continue
            if re.search(r"\b(background|fill)\(\s*(Color)?\.white\s*[,)]", code) or "Color.white.shadow(" in code:
                bad.append(f"{name}:{i}: {code.strip()[:90]}")
        self.assertEqual(bad, [], "use SE.surface: plain white is a white slab in dark mode")

    def test_the_allowed_whites_are_still_there(self):
        """An exception that no longer matches anything should be deleted."""
        texts = dict(sources())
        for name in WHITE_ALLOWED:
            self.assertRegex(texts[name], r"(background|fill)\(\s*Color\.white", name)

    def test_the_card_helper_uses_the_surface(self):
        with open(THEME, encoding="utf-8") as f:
            self.assertIn("self.background(SE.surface)", f.read())


class InksAndFillsAreNotMixedUp(unittest.TestCase):
    FG = r"(foregroundStyle|foregroundColor|seText)\("

    def test_text_never_takes_a_fill_token(self):
        """foregroundStyle(SE.royal) is teal that white text can sit on: too
        dark to read on a dark card. Text takes SE.royalInk."""
        bad = []
        for name, i, code in code_lines():
            for m in re.finditer(self.FG, code):
                # the argument list of this call only
                depth, j = 1, m.end()
                while j < len(code) and depth:
                    depth += code[j] == "("
                    depth -= code[j] == ")"
                    j += 1
                arg = code[m.end():j]
                if re.search(r"SE\.(royal|good|warn|bad)\b(?!Ink|Dark)", arg):
                    bad.append(f"{name}:{i}: {arg.strip()[:80]}")
        self.assertEqual(bad, [])

    def test_inks_and_fills_are_the_same_colour_in_light_mode(self):
        p = pairs()
        for fill in FILLS:
            self.assertEqual(p[fill][0], p[fill + "Ink"][0], f"{fill} and {fill}Ink should match in light mode")


class DarkContrast(unittest.TestCase):
    def setUp(self):
        self.p = pairs()

    def test_every_ink_reads_on_the_dark_card_and_canvas(self):
        for ink in INKS:
            for ground in ("surface", "canvas"):
                c = contrast(self.p[ink][1], self.p[ground][1])
                self.assertGreaterEqual(c, 4.5, f"{ink} on dark {ground} is {c:.2f}:1")

    def test_white_text_reads_on_every_dark_fill(self):
        for fill in FILLS + ("navy",):
            c = contrast(0xFFFFFF, self.p[fill][1])
            self.assertGreaterEqual(c, 4.5, f"white on dark {fill} is {c:.2f}:1")

    def test_chip_text_reads_on_its_dark_wash(self):
        for ink, wash in (("goodInk", "goodWash"), ("warnInk", "warnWash"), ("plusInk", "plusWash"),
                          ("mintInk", "mintWash"), ("navyInk", "paleBlue"), ("ink", "badge"), ("ink2", "badge")):
            c = contrast(self.p[ink][1], self.p[wash][1])
            self.assertGreaterEqual(c, 4.5, f"{ink} on dark {wash} is {c:.2f}:1")

    def test_a_card_can_be_told_from_the_canvas(self):
        self.assertNotEqual(self.p["surface"][1], self.p["canvas"][1])
        self.assertGreater(luminance(self.p["surface"][1]), luminance(self.p["canvas"][1]))


class LightModeIsUnchanged(unittest.TestCase):
    def test_every_light_value_is_the_one_that_shipped(self):
        p = pairs()
        for name, hexv in SHIPPED_LIGHT.items():
            self.assertIn(name, p, f"{name} is no longer a light/dark pair")
            self.assertEqual(p[name][0], hexv, f"{name}'s light value changed")

    def test_the_surface_is_white_in_light_mode(self):
        self.assertEqual(pairs()["surface"][0], 0xFFFFFF)


if __name__ == "__main__":
    unittest.main()
