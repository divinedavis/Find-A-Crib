#!/usr/bin/env python3
"""Writes the reviewed translations in scripts/l10n/overrides/<lang>.json
into Shared/Localizable.xcstrings with state "translated", which
scripts/l10n/translate.sh never overwrites (see review_flags.py for why they
exist). Run it after translate.sh; it is idempotent.

    scripts/l10n/apply_overrides.py            # every overrides file
    scripts/l10n/apply_overrides.py de ja      # some languages

An override is "english key": "translation", or for a plural key
{"one": …, "other": …} with the categories that language uses. A key no
longer in the catalog is reported and skipped; a translation whose
placeholders don't match the English is refused (the run fails).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "Shared" / "Localizable.xcstrings"
OVERRIDES = ROOT / "scripts" / "l10n" / "overrides"
sys.path.insert(0, str(ROOT / "scripts"))
from test_localizable_catalog import signature  # noqa: E402  (same placeholder grammar)


def unit(value: str) -> dict:
    return {"stringUnit": {"state": "translated", "value": value}}


def apply(lang: str, overrides: dict, strings: dict) -> tuple[int, list[str], list[str]]:
    applied, missing, refused = 0, [], []
    for key, value in overrides.items():
        entry = strings.get(key)
        if entry is None:
            missing.append(key)
            continue
        en = entry.get("localizations", {}).get("en", {}).get("variations", {}).get("plural")
        english_other = en["other"]["stringUnit"]["value"] if en else key
        want = signature(english_other)
        if isinstance(value, dict):
            if "other" not in value or any(
                any(signature(v).count(g) > want.count(g) for g in signature(v)) for v in value.values()
            ):
                refused.append(f"{key!r}: {value!r}")
                continue
            loc = {"variations": {"plural": {cat: unit(v) for cat, v in value.items()}}}
        else:
            if signature(value) != want:
                refused.append(f"{key!r}: {value!r}")
                continue
            loc = unit(value)
        entry.setdefault("localizations", {})[lang] = loc
        applied += 1
    return applied, missing, refused


def main() -> int:
    langs = sys.argv[1:] or sorted(p.stem for p in OVERRIDES.glob("*.json"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    failed = False
    for lang in langs:
        path = OVERRIDES / f"{lang}.json"
        if not path.exists():
            print(f"{lang}: no overrides")
            continue
        applied, missing, refused = apply(lang, json.loads(path.read_text(encoding="utf-8")), catalog["strings"])
        print(f"{lang}: {applied} reviewed translations applied"
              + (f", {len(missing)} keys gone from the catalog" if missing else ""))
        for r in refused:
            print(f"  refused (placeholders): {r}", file=sys.stderr)
        failed |= bool(refused)
    with CATALOG.open("w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2, sort_keys=True, separators=(",", " : "))
        f.write("\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
