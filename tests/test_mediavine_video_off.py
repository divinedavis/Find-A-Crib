"""The Mediavine opt-out div that turns the Universal (video) Player off
(owner, 2026-10-26) is on the map page exactly once, with both switches set,
and build_city_pages carries it to every city page."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIV = re.compile(r'<div id="ad-management-config-settings"([^>]*)>')


def check(html, name):
    found = DIV.findall(html)
    assert len(found) == 1, f"{name}: expected one opt-out div, got {len(found)}"
    attrs = found[0]
    assert 'data-blocklist-universal-player-desktop="1"' in attrs, name
    assert 'data-blocklist-universal-player-mobile="1"' in attrs, name


def test_map_page_turns_video_player_off():
    check((ROOT / "index.html").read_text(), "index.html")


def test_city_pages_carry_it():
    subprocess.run([sys.executable, "build_city_pages.py"], cwd=ROOT, check=True,
                   capture_output=True)
    for c in ("la", "sf", "dc", "westchester"):
        check((ROOT / c / "index.html").read_text(), f"{c}/index.html")
