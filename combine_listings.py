#!/usr/bin/env python3
"""Overlay Apify per-borough data onto the Zumper baseline -> listings.json.

Hybrid pipeline:
  listings_zumper.json  (nightly, free, all 5 boroughs)   = base
  listings_apify.json   (monthly per-borough, paid)       = overlay (wins)
  listings.json         (served by the site)              = base + overlay

Per building, Apify wins on conflict (it's the higher-coverage source for the
boroughs it has scraped); Zumper fills in everything Apify hasn't covered. The
union maximizes coverage. Safe to run every night after the Zumper scrape and
again after each Apify run — it's idempotent.
"""
import json
import time
from pathlib import Path

HERE = Path(__file__).parent
ZUMPER = HERE / "listings_zumper.json"
APIFY = HERE / "listings_apify.json"
OUT = HERE / "listings.json"
MAPS = ("counts", "urls", "prices", "beds")


def load(p):
    return json.loads(p.read_text()) if p.exists() else {}


def main():
    z, a = load(ZUMPER), load(APIFY)
    out = {}
    for m in MAPS:
        # base = Zumper, then Apify overrides/adds per building (Apify wins)
        out[m] = {**z.get(m, {}), **a.get(m, {})}
    out["updated"] = max(z.get("updated", 0), a.get("updated", 0)) or int(time.time())
    out["updated_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00",
                                       time.gmtime(out["updated"]))
    OUT.write_text(json.dumps(out, separators=(",", ":")))

    from collections import Counter
    by_boro = Counter(k[:1] for k in out["prices"])
    print(f"combined -> listings.json: {len(out['prices'])} priced buildings "
          f"(zumper {len(z.get('prices', {}))}, apify {len(a.get('prices', {}))}); "
          f"by borough {dict(by_boro)}")


if __name__ == "__main__":
    main()
