"""The droplet's two Python venvs, as pinned in deploy/{api,jobs}/requirements.txt
(security pass 2026-11-05). Those files exist so Dependabot alerts can see what
the server runs; these checks keep them parseable, keep deploy/install_jobs.sh's
fresh-venv pins equal to them, and keep the versions above the releases whose
CVEs were fixed that day (pypdf parses user-uploaded lease PDFs; Pillow decodes
photos fetched from third-party listing sites)."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
PIN = re.compile(r"^([A-Za-z0-9_.\-\[\]]+)==([0-9][0-9A-Za-z.+\-]*)$")

# package -> first release with every known advisory fixed (osv.dev, 2026-11-05)
FLOORS = {
    "api": {"pypdf": "6.21.4", "werkzeug": "3.1.9"},
    "jobs": {"pypdf": "6.21.4", "pillow": "13.0.0", "pyjwt": "2.15.0",
             "requests": "2.33.0", "certifi": "2026.10.18", "setuptools": "84.1.0"},
}


def _ver(v):
    return tuple(int(x) for x in re.findall(r"\d+", v))


def pins(which):
    out = {}
    for line in (ROOT / "deploy" / which / "requirements.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = PIN.match(line)
        assert m, f"deploy/{which}/requirements.txt: not an exact pin: {line!r}"
        out[re.sub(r"\[.*\]", "", m.group(1)).lower().replace("_", "-")] = m.group(2)
    return out


def test_requirements_are_exact_pins_above_the_fixed_floors():
    for which, floors in FLOORS.items():
        have = pins(which)
        for pkg, floor in floors.items():
            assert pkg in have, f"{pkg} missing from deploy/{which}/requirements.txt"
            assert _ver(have[pkg]) >= _ver(floor), f"{which}: {pkg} {have[pkg]} < {floor}"


def test_install_jobs_fresh_venv_pins_match_the_jobs_manifest():
    src = (ROOT / "deploy" / "install_jobs.sh").read_text()
    jobs = pins("jobs")
    found = re.findall(r'"([A-Za-z0-9_\-]+)(?:\[[a-z]+\])?==([0-9.]+)"', src)
    assert found, "install_jobs.sh no longer pins any package"
    for pkg, ver in found:
        key = pkg.lower().replace("_", "-")
        assert jobs.get(key) == ver, f"install_jobs.sh pins {pkg}=={ver}, manifest has {jobs.get(key)}"
