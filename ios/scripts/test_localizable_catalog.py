"""Shared/Localizable.xcstrings stays safe to ship in every language.

A translation whose placeholders don't match the English crashes or garbles
the string at run time (String(format:) reads the wrong argument type), so
every unit is checked against its English source here, without a simulator:

- a plain translation consumes exactly the English arguments, by number and
  type (positional %2$@ … %1$@ reorderings are fine);
- a plural form may leave the count out ("ein Artikel"), but never adds one
  or changes a type, and every language with English plural forms has the
  "other" form;
- "Find A Crib" is never translated away;
- a language Xcode would offer (any unit present) is one the app ships.

The same placeholder grammar as scripts/l10n/translate.swift.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "Shared" / "Localizable.xcstrings"

PLACEHOLDER = re.compile(
    r"%%|%#@[A-Za-z0-9_]+@|%(?:\d+\$)?[-+0#]*(?:\d+|\*)?(?:\.\d+)?(?:hh|h|ll|l|q|L|z|t|j)?[@dDiuUxXoOfFeEgGcCsSaAp]"
)
SHIPPED = {"en", "es", "ko", "ru", "zh-Hans", "zh-Hant"}


def signature(s: str) -> list[str]:
    """Each argument the format consumes as "number:type", %% as "-:%"."""
    out, nxt = [], 1
    for m in PLACEHOLDER.finditer(s):
        t = m.group(0)
        if t == "%%":
            out.append("-:%")
            continue
        if t.startswith("%#@"):
            out.append(f"{nxt}:{t}")
            nxt += 1
            continue
        body = t[1:]
        pos = re.match(r"(\d+)\$(.*)", body)
        if pos:
            n, conv = int(pos.group(1)), pos.group(2)
        else:
            n, conv = nxt, body
            nxt += 1
        out.append(f"{n}:{conv.lstrip('-+0#*.0123456789')}")
    return sorted(out)


def units(loc: dict) -> list[tuple[str, str]]:
    """(plural category or "", value) for a localization."""
    if "stringUnit" in loc:
        return [("", loc["stringUnit"]["value"])]
    plural = loc.get("variations", {}).get("plural", {})
    return [(cat, v["stringUnit"]["value"]) for cat, v in plural.items() if "stringUnit" in v]


def load() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))["strings"]


def test_placeholders_match_english():
    bad = []
    for key, entry in load().items():
        locs = entry.get("localizations", {})
        english = locs.get("en")
        source = dict(units(english)) if english else {"": key}
        other = source.get("other", source.get(""))
        want = signature(other)
        for lang, loc in locs.items():
            for cat, value in units(loc):
                got = signature(value)
                if cat:   # a plural form may drop the count, nothing else
                    if any(got.count(g) > want.count(g) for g in got):
                        bad.append(f"{lang}[{cat}] {key!r}: {value!r}")
                elif got != want:
                    bad.append(f"{lang} {key!r}: {value!r}")
    assert not bad, f"{len(bad)} translations change placeholders:\n" + "\n".join(bad[:20])


def test_plural_keys_have_other_in_every_language():
    bad = []
    for key, entry in load().items():
        locs = entry.get("localizations", {})
        if "variations" not in locs.get("en", {}):
            continue
        for lang, loc in locs.items():
            plural = loc.get("variations", {}).get("plural")
            if plural is not None and "other" not in plural:
                bad.append(f"{lang} {key!r}")
    assert not bad, "plural forms without 'other':\n" + "\n".join(bad)


def test_app_name_is_never_translated():
    bad = []
    for key, entry in load().items():
        if "Find A Crib" not in key:
            continue
        for lang, loc in entry.get("localizations", {}).items():
            for cat, value in units(loc):
                if "Find A Crib" not in value:
                    bad.append(f"{lang} {key!r}: {value!r}")
    assert not bad, "\n".join(bad[:20])


def test_only_shipped_languages():
    langs = {lang for e in load().values() for lang in e.get("localizations", {})}
    assert langs <= SHIPPED, f"unexpected languages: {sorted(langs - SHIPPED)}"


def test_signature_grammar():
    assert signature("%lld items: Total") == ["1:lld"]
    assert signature("%2$@ von %1$@") == signature("%1$@ by %2$@")
    assert signature("10%% off %@") == ["-:%", "1:@"]
    assert signature("Save 10% or more") == []   # "% o" is not a placeholder
