#!/usr/bin/env python3
"""Copy Marracat's holiday list into Find A Crib (owner, 2026-10-23: "use
the same days as marracat"): dates, theme spans, colours, splash line, mark
and icon bands. Marracat's event and collection fields stay behind; Find A
Crib makes no App Store events for holidays (App Review rejected events that
bring nothing new under 2.3.13 on 2026-10-20).

    python3 scripts/sync_holidays.py [path/to/Marracat/Resources/holidays.json]

Then re-run scripts/holiday_app_icons.py --xcassets.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path.home() / "projects/Marracat/Marracat/Resources/holidays.json")
KEEP = ["id", "name", "kind", "rule", "date", "theme", "line", "disc", "mark", "tab", "icon_bands", "effect"]

out = {
    "_about": "Holidays Find A Crib dresses up for: a copy of Marracat's list (scripts/sync_holidays.py), so both apps match on "
              "the same day. date: month + day, or the nth ISO weekday (1 = Monday) of the month (nth -1 = last), plus offset days. "
              "theme: the days around it (from/to) the splash, skyline, Map pill, tab bar and icon wear it; on overlapping days the "
              "shortest theme wins. icon_bands: [colour, weight] stripes behind the house on the Home Screen icon (AppIcon-<id>).",
    "holidays": [],
}
for h in json.loads(SRC.read_text())["holidays"]:
    o = {k: h[k] for k in KEEP if k in h}
    o["icon"] = "AppIcon-" + h["id"]
    out["holidays"].append(o)
(ROOT / "FindACrib/Resources/holidays.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
print(f"{len(out['holidays'])} holidays")
