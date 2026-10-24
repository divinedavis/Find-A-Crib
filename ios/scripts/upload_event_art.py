#!/usr/bin/env python3
"""Render and upload the logo event art (make_event_assets.py --theme logo)
to the Asset Library, once per look; asc_events_auto.py then reuses it
every year, so approved art never waits on review again.

    ~/.venvs/spendcap/bin/python scripts/upload_event_art.py everyday halloween thanksgiving

"everyday" is the teal field for the non-holiday events; any other name is
a holiday id from holidays.json. Owner, 2026-10-24: "we should always have
our logo on the event card and event details".
"""
import subprocess
import sys
from pathlib import Path

from asc_creative_assets import _cfg, images, upload_one

HERE = Path(__file__).resolve().parent
APP = _cfg()["ASC_APP_ID"]
PY = Path.home() / ".venvs/dhcr-map/bin/python"   # Pillow + the brand fonts' venv


def ref(look, kind):
    """Asset Library name of a look's card or details art."""
    size = "3840x2160" if kind == "card" else "2160x3840"
    return f"fac-events-logo/{look}/{kind}-{size}.png"


def main():
    have = {i["attributes"].get("referenceName") for i in images(APP)
            if i["attributes"].get("state") != "ARCHIVED"}
    for look in sys.argv[1:]:
        out = Path.home() / "Downloads/ASC-creative-assets/findacrib/event-logo" / look
        cmd = [str(PY), str(HERE / "make_event_assets.py"), str(out), "--theme", "logo"]
        if look != "everyday":
            cmd += ["--holiday", look]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
        for kind in ("card", "details"):
            r = ref(look, kind)
            if r in have:
                print(f"already  {r}")
                continue
            iid, state, _ = upload_one(APP, out / Path(r).name, r)
            print(f"uploaded {r} ({state})")


if __name__ == "__main__":
    main()
