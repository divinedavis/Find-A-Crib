#!/usr/bin/env python3
"""The short strings of one language that need a person's (or Claude's) eye.

Apple's on-device translation does well on sentences and badly on bare
labels it has no context for: "Cart" came back as "Kutsche" (a carriage),
"Block" as "Datenbaustein", "Close" as "Ende" (2026-10-14). The owner's call
that day: keep Apple's translations for sentences, review the short labels
by hand, and keep the reviewed ones in scripts/l10n/overrides/<lang>.json,
which scripts/l10n/apply_overrides.py writes into the catalog as
"translated" so translate.sh never touches them again.

    scripts/l10n/review_flags.py de            # queue -> build/l10n/review-de.json
    scripts/l10n/review_flags.py de --stats    # counts only

A queue entry: the English (plural forms when it has them), the developer
comment (where it appears), Apple's translation and its back-translation.
Keys already in overrides/<lang>.json are left out.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "Shared" / "Localizable.xcstrings"
STATE = ROOT / "scripts" / "l10n" / "translation-state.json"
OVERRIDES = ROOT / "scripts" / "l10n" / "overrides"

# Short = a label: few words, nothing that reads as a sentence.
MAX_WORDS = 4
MAX_CHARS = 36


def english_forms(key: str, entry: dict) -> dict[str, str]:
    en = entry.get("localizations", {}).get("en", {})
    plural = en.get("variations", {}).get("plural")
    if plural:
        return {cat: v["stringUnit"]["value"] for cat, v in plural.items()}
    return {"": en.get("stringUnit", {}).get("value", key)}


def is_short(text: str) -> bool:
    return len(text.split()) <= MAX_WORDS and len(text) <= MAX_CHARS


def translation(entry: dict, lang: str):
    loc = entry.get("localizations", {}).get(lang)
    if not loc:
        return None
    if "stringUnit" in loc:
        return loc["stringUnit"]["value"]
    plural = loc.get("variations", {}).get("plural", {})
    return {cat: v["stringUnit"]["value"] for cat, v in plural.items()}


def queue(lang: str) -> list[dict]:
    strings = json.loads(CATALOG.read_text(encoding="utf-8"))["strings"]
    state = json.loads(STATE.read_text(encoding="utf-8")).get(lang, {}) if STATE.exists() else {}
    path = OVERRIDES / f"{lang}.json"
    done = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    out = []
    for key in sorted(strings):
        entry = strings[key]
        if entry.get("shouldTranslate") is False or key in done:
            continue
        forms = english_forms(key, entry)
        if not is_short(forms.get("other", forms.get(""))):
            continue
        item = {"key": key, "comment": entry.get("comment", "")}
        item["english"] = forms if "other" in forms else forms[""]
        item["apple"] = translation(entry, lang)
        item["back"] = state.get(key, {}).get("back")
        out.append(item)
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    lang = sys.argv[1]
    q = queue(lang)
    if "--stats" in sys.argv:
        print(f"{lang}: {len(q)} short strings to review")
        return 0
    out = ROOT / "build" / "l10n" / f"review-{lang}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(q, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{lang}: {len(q)} short strings -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
