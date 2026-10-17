#!/usr/bin/env python3
"""Put back what Apple's translation drops at the edges of a string.

Find A Crib builds many lines by joining pieces (" · synced", " and ",
"Sources: "), so a translation that loses the English string's leading or
trailing spaces glues words together. A fragment that starts lowercase in
English ("with bedbugs", "; some have…") is mid-sentence, so a machine
translation that capitalised it is lowercased again. Reviewed units
(state "translated", from overrides/) are left alone. Run after
translate.sh and apply_overrides.py; idempotent.

    scripts/l10n/keep_edges.py
"""
import json
import re
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[2] / "Shared" / "Localizable.xcstrings"


def fix(english: str, value: str) -> str:
    lead = re.match(r"\s*", english).group(0)
    trail = re.search(r"\s*$", english).group(0)
    core = value.strip()
    if english.strip()[:1].islower() and core[:1].isupper() and not core[:2].isupper():
        core = core[0].lower() + core[1:]
    return lead + core + trail


def main():
    cat = json.loads(CATALOG.read_text())
    changed = 0
    for key, entry in cat["strings"].items():
        en_forms = (entry.get("localizations", {}).get("en", {}).get("variations", {}).get("plural", {}))
        for lang, loc in entry.get("localizations", {}).items():
            if lang == "en":
                continue
            units = [("", loc)] if "stringUnit" in loc else list(loc.get("variations", {}).get("plural", {}).items())
            for cat_name, u in units:
                su = u.get("stringUnit")
                if not su or su.get("state") == "translated":
                    continue
                english = en_forms.get(cat_name, en_forms.get("other", {})).get("stringUnit", {}).get("value", key) if cat_name else key
                new = fix(english, su["value"])
                if new != su["value"]:
                    su["value"] = new
                    changed += 1
    CATALOG.write_text(json.dumps(cat, ensure_ascii=False, indent=2, sort_keys=True, separators=(",", " : ")) + "\n")
    print(f"edges fixed in {changed} units")


if __name__ == "__main__":
    main()
