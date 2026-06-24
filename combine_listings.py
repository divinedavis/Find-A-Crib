#!/usr/bin/env python3
"""Accumulate new buildings into listings.json without touching existing ones.

The served listings.json is a STICKY MASTER: once a building has a price we
keep it as-is. Each run only *adds* buildings we don't already have, pulled
from the latest scrapes:

  listings.json        (served)            = sticky master, accumulates
  listings_zumper.json (monthly, free)     = candidate source (all boroughs)
  listings_apify.json  (per-borough, paid) = candidate source (Apify wins vs Zumper)

Per building: if it's already in the master, the master's values win (price is
never overwritten); only buildings absent from the master get added from the
candidates. This is "only find new pricing for apartments we don't already
have" — coverage grows monotonically, existing prices stay put.

Idempotent: re-running adds nothing new. (Note: prices don't refresh and sold/
delisted buildings aren't pruned — that's the intended sticky behavior.)
"""
import json
import time
from pathlib import Path

HERE = Path(__file__).parent
MASTER = HERE / "listings.json"
ZUMPER = HERE / "listings_zumper.json"
APIFY = HERE / "listings_apify.json"
MAPS = ("counts", "urls", "prices", "beds")


def load(p):
    return json.loads(p.read_text()) if p.exists() else {}


def main():
    master, z, a = load(MASTER), load(ZUMPER), load(APIFY)
    out = {}
    for m in MAPS:
        candidates = {**z.get(m, {}), **a.get(m, {})}   # Apify wins vs Zumper
        out[m] = {**candidates, **master.get(m, {})}     # master sticky; fill gaps only
    out["updated"] = max(master.get("updated", 0), z.get("updated", 0),
                         a.get("updated", 0)) or int(time.time())
    out["updated_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00",
                                       time.gmtime(out["updated"]))
    MASTER.write_text(json.dumps(out, separators=(",", ":")))

    from collections import Counter
    added = len(out["prices"]) - len(master.get("prices", {}))
    print(f"accumulate -> listings.json: {len(out['prices'])} priced buildings "
          f"(+{added} new; master kept {len(master.get('prices', {}))}); "
          f"by borough {dict(Counter(k[:1] for k in out['prices']))}")


if __name__ == "__main__":
    main()
