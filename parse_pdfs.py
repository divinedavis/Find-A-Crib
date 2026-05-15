#!/usr/bin/env python3
"""Parse the DHCR Manhattan + Brooklyn building PDFs into a single JSON of records.

Each record carries: borough, zip, address, block, lot, bbl, status fields.
"""
import fitz
import json
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent

# borough numeric prefix used in NYC BBL
BOROUGH_CODE = {"manhattan": 1, "brooklyn": 3}

HEADER_FIELDS = [
    "ZIP", "BLDGNO1", "STREET1", "STSUFX1",
    "BLDGNO2", "STREET2", "STSUFX2",
    "CITY", "COUNTY", "STATUS1", "STATUS2", "STATUS3",
    "BLOCK", "LOT",
]


def header_x_positions(page):
    """Return dict {field: x0} from the header row of a page. None if not found."""
    words = page.get_text("words")
    rows = defaultdict(list)
    for x0, y0, x1, y1, text, *_ in words:
        rows[round(y0)].append((x0, text))
    for y in sorted(rows):
        tokens = sorted(rows[y])
        token_text = [t for _, t in tokens]
        if token_text[:3] == ["ZIP", "BLDGNO1", "STREET1"]:
            return {t: x for x, t in tokens if t in HEADER_FIELDS}, y
    return None, None


def snap_words_to_columns(words_xy, col_positions):
    """words_xy: list of (x0, text). col_positions: dict field -> x. Returns dict field -> joined text."""
    cols = sorted(col_positions.items(), key=lambda kv: kv[1])
    field_names = [c[0] for c in cols]
    field_xs = [c[1] for c in cols]
    bucket = defaultdict(list)
    for x, t in sorted(words_xy):
        # find nearest column whose x is <= word x (last column wins for words past last header x)
        idx = 0
        for i, fx in enumerate(field_xs):
            if x + 1 >= fx:
                idx = i
            else:
                break
        bucket[field_names[idx]].append(t)
    return {f: " ".join(bucket[f]).strip() for f in field_names}


def parse_pdf(path: Path, borough: str):
    doc = fitz.open(path)
    out = []
    bcode = BOROUGH_CODE[borough]
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        col_positions, header_y = header_x_positions(page)
        if not col_positions:
            continue
        words = page.get_text("words")
        rows = defaultdict(list)
        for x0, y0, x1, y1, text, *_ in words:
            if y0 <= header_y + 4:  # skip title + header
                continue
            rows[round(y0)].append((x0, text))
        for y in sorted(rows):
            row = snap_words_to_columns(rows[y], col_positions)
            zip_code = row.get("ZIP", "").strip()
            block = row.get("BLOCK", "").strip()
            lot = row.get("LOT", "").strip()
            if not (zip_code.isdigit() and block.isdigit() and lot.isdigit()):
                continue
            address1 = " ".join(p for p in [row.get("BLDGNO1"), row.get("STREET1"), row.get("STSUFX1")] if p).strip()
            address2 = " ".join(p for p in [row.get("BLDGNO2"), row.get("STREET2"), row.get("STSUFX2")] if p).strip()
            statuses = [row.get(k, "").strip() for k in ("STATUS1", "STATUS2", "STATUS3")]
            statuses = [s for s in statuses if s]
            bbl = bcode * 10**9 + int(block) * 10**4 + int(lot)
            out.append({
                "borough": borough,
                "zip": zip_code,
                "address": address1,
                "address_alt": address2 or None,
                "block": int(block),
                "lot": int(lot),
                "bbl": str(bbl),
                "statuses": statuses,
            })
    doc.close()
    return out


def main():
    all_records = []
    for borough, fname in [
        ("manhattan", "2024-DHCR-Bldg-File-Manhattan.pdf"),
        ("brooklyn", "2024-DHCR-Bldg-File-Brooklyn.pdf"),
    ]:
        path = HERE / fname
        print(f"Parsing {fname}...")
        recs = parse_pdf(path, borough)
        print(f"  {len(recs)} records")
        all_records.extend(recs)

    # de-dup by bbl (some buildings repeat across pages)
    seen = {}
    for r in all_records:
        seen.setdefault(r["bbl"], r)
    unique = list(seen.values())
    print(f"Total unique BBLs: {len(unique)}")

    out_path = HERE / "buildings.json"
    out_path.write_text(json.dumps(unique))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
