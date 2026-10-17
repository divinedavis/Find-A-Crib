#!/usr/bin/env python3
"""Find A Crib's housing terms, forced into every machine translation.

Apple's model picks the everyday sense of a word: a housing lottery became
a gambling ticket (zh 彩票, ko 복권), a Section 8 voucher a store coupon
(es cupones, zh 代金券/优惠券), bedbugs fleas or cockroaches. NYC's own
translated material says 抽签 / 추첨 / vales / 臭虫 / 빈대, and so does this
app. Reviewed units (state "translated") are left alone. Run after
translate.sh and apply_overrides.py; idempotent.

    scripts/l10n/glossary.py
"""
import json
import re
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[2] / "Shared" / "Localizable.xcstrings"

# (language, English key must match (regex, case-insensitive) or None, wrong, right)
RULES = [
    ("zh-Hans", None, r"彩票", "抽签"),
    ("zh-Hant", None, r"彩票", "抽籤"),
    ("ko", None, r"복권", "추첨"),
    ("zh-Hans", r"voucher|section 8", r"代金券|优惠券", "住房券"),
    ("zh-Hant", r"voucher|section 8", r"代金券|優惠券|優惠卷", "住房券"),
    ("es", r"voucher|section 8", r"cupones", "vales"),
    ("es", r"voucher|section 8", r"cupón", "vale"),
    ("zh-Hans", r"bed ?bug", r"床蟑螂|蟑螂|跳蚤", "臭虫"),
    ("zh-Hant", r"bed ?bug", r"床蟑螂|蟑螂|跳蚤", "臭蟲"),
    ("ko", r"bed ?bug", r"기생충|벼룩|바퀴벌레", "빈대"),
    ("es", r"bed ?bug", r"pulgas de cama|pulgas|cucarachas", "chinches"),
    ("es", r"roach", r"caracol(es)?", "cucarachas"),
    ("es", r"re-rental", r"rearrendamientos?|realquiler(es)?|subarriendos?", "re-alquileres"),
    ("es", r"borough(?!.*neighborhood)", r"\bbarrios\b", "condados"),
    ("es", r"borough(?!.*neighborhood)", r"\bbarrio\b", "condado"),
    ("es", r"borough(?!.*neighborhood)", r"\bdistritos?\b", "condados"),
]


def main():
    cat = json.loads(CATALOG.read_text())
    changed = 0
    for key, entry in cat["strings"].items():
        for lang, keypat, wrong, right in RULES:
            if keypat and not re.search(keypat, key, re.I):
                continue
            # "roaches … bedbugs" in one sentence: the bedbug fix would turn the
            # roaches into bedbugs too, so those sentences are reviewed by hand.
            if "bed" in (keypat or "") and re.search(r"roach", key, re.I):
                continue
            loc = entry.get("localizations", {}).get(lang)
            if not loc:
                continue
            units = [loc] if "stringUnit" in loc else list(loc.get("variations", {}).get("plural", {}).values())
            for u in units:
                su = u["stringUnit"]
                if su.get("state") == "translated":
                    continue
                new = re.sub(wrong, right, su["value"])
                if new != su["value"]:
                    su["value"] = new
                    changed += 1
    CATALOG.write_text(json.dumps(cat, ensure_ascii=False, indent=2, sort_keys=True, separators=(",", " : ")) + "\n")
    print(f"glossary fixed {changed} units")


if __name__ == "__main__":
    main()
