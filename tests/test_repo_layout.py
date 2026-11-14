"""The repo layout the crons, the API deploy and the docs depend on (2026-11-13).

Scripts moved from the repo root into pipeline/ (jobs, builders, shared
modules) and api/ (the Flask server and its auth bits). A cron line or a
deploy list that still names an old path fails silently on the droplet: the
job just never runs. These tests make it fail here instead."""
import re
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKOUT = "/root/Find-A-Crib"


def _cron_lines():
    for f in sorted((ROOT / "deploy").glob("cron-rentmap-*")):
        for line in f.read_text().splitlines():
            s = line.strip()
            # Paused lines (#PAUSED-...) still name real scripts: check them too.
            if s.startswith("#PAUSED-"):
                s = s.split(" ", 1)[1]
            elif not s or s.startswith("#") or "=" in s.split()[0]:
                continue
            yield f.name, s


def _scripts_in(line):
    """Every repo script a cron line runs, as a path relative to the checkout."""
    out = []
    cwd_is_checkout = f"cd {CHECKOUT}" in line and f"cd {CHECKOUT}/" not in line
    for tok in shlex.split(line.replace("'", " ").replace('"', " "), posix=True):
        if tok.startswith(CHECKOUT + "/") and tok.endswith((".py", ".sh")):
            out.append(tok[len(CHECKOUT) + 1:])
        elif cwd_is_checkout and re.fullmatch(r"[\w./-]+\.(py|sh)", tok) and not tok.startswith("/"):
            out.append(tok)
    return out


def test_no_scripts_left_at_the_repo_root():
    loose = sorted(p.name for p in ROOT.glob("*") if p.suffix in (".py", ".sh") and p.is_file()
                   and not p.name.startswith("."))
    assert loose == [], f"put new scripts in pipeline/ (jobs, builders) or api/ (the server): {loose}"


def test_api_holds_only_the_server_and_its_auth():
    assert sorted(p.name for p in (ROOT / "api").glob("*.py")) == ["api_server.py", "issue_api_key.py", "passkeys.py"]


def test_every_cron_line_names_a_script_that_exists():
    seen = 0
    for name, line in _cron_lines():
        for rel in _scripts_in(line):
            seen += 1
            assert (ROOT / rel).is_file(), f"{name}: {rel} does not exist in the repo ({line})"
    assert seen >= 20, seen   # the parser found the jobs at all


def test_cron_jobs_run_scripts_from_pipeline_not_the_root():
    for name, line in _cron_lines():
        for rel in _scripts_in(line):
            assert "/" in rel, f"{name}: {rel} is a bare root path; scripts live in pipeline/ ({line})"


def test_every_api_module_is_in_api_or_pipeline():
    text = (ROOT / "scripts" / "deploy_api.sh").read_text()
    files = re.search(r"^FILES=\(([^)]*)\)", text, re.M).group(1).split()
    assert "api_server.py" in files
    for f in files:
        assert (ROOT / "api" / f).is_file() or (ROOT / "pipeline" / f).is_file(), f


def test_shell_wrappers_run_pipeline_scripts():
    for sh in (ROOT / "pipeline").glob("*.sh"):
        for line in sh.read_text().splitlines():
            if line.lstrip().startswith("#"):
                continue
            for m in re.finditer(r"(?:python3?|\"\$PY\")\s+([\w./-]+\.py)", line):
                assert (ROOT / m.group(1)).is_file(), f"{sh.name}: {m.group(1)}"


def _tracked_root_files():
    """Files git tracks at the top level. Ignored, generated data (buildings.json,
    featured.json, ...) is allowed to sit there on a workstation or the droplet;
    only what the repo itself carries is checked."""
    import os
    import subprocess
    # Under a git hook GIT_DIR/GIT_INDEX_FILE point at the pushing checkout;
    # strip them so ls-files reads this tree (reference: hooks flip core.bare).
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, env=env, check=True,
                             capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return sorted(p for p in out.splitlines() if "/" not in p)


def test_no_data_files_left_at_the_repo_root():
    """Stage 2 (2026-11-13): committed data lives in data/ (served URLs unchanged)."""
    files = _tracked_root_files()
    if files is None:
        return  # not a git checkout (a flat copy); nothing to check
    loose = [f for f in files if f.endswith((".json", ".geojson", ".pdf", ".pem", ".csv"))]
    assert loose == [], f"put committed data in data/ (and keep the served URL in the deploy step): {loose}"


def test_moved_data_is_where_the_scripts_look():
    for rel in ("data/buildings.min.json", "data/s8.json", "data/fmr.json", "data/hcr.json",
                "data/housing_law_firms.json", "data/rerental_pages.json", "data/marketing_agents.json",
                "data/landlords.json", "data/council_districts.json", "data/council_districts.geojson",
                "data/nta_2020.geojson", "data/owner_vacancy_pages.json", "data/agent_buildings.json",
                "pipeline/hcr_chain.pem", "docs/BACKLOG.md"):
        assert (ROOT / rel).is_file(), rel
    assert len(list((ROOT / "data" / "dhcr").glob("2024-DHCR-Bldg-File-*.pdf"))) == 5


def test_bots_commit_the_state_files_at_their_new_paths():
    for sh in ("pipeline/rerental_daily.sh", "pipeline/check_rerentals.sh"):
        text = (ROOT / sh).read_text()
        assert "git add -A data/rerental_pages.json data/marketing_agents.json" in text, sh


def test_the_dhcr_list_checker_still_sees_the_2024_pdfs():
    # It globs for *-DHCR-Bldg-File-*.pdf; after the move a root glob found
    # nothing and the monthly cron would have exited without checking.
    import sys
    sys.path.insert(0, str(ROOT / "pipeline"))
    import check_dhcr_list
    assert check_dhcr_list.have_year() == 2024


# Stage 3 (2026-11-13): everything served at findacrib.com lives in web/, laid
# out like the docroot, so the top level reads like a project, not a site dump.
TOP_LEVEL_FILES = {".gitignore", ".gitleaks.toml", "README.md", "LICENSE.md", "CONTRIBUTING.md",
                   "SECURITY.md", "AGENTS.md", "CLAUDE.md"}
TOP_LEVEL_DIRS = {".github", ".githooks", "api", "data", "db", "deploy", "docs", "growth", "ios",
                  "marketing", "monitoring", "pipeline", "scripts", "supabase", "tests", "web"}


def test_top_level_is_only_the_allowlist():
    files = _tracked_root_files()
    if files is None:
        return
    extra = sorted(set(files) - TOP_LEVEL_FILES)
    assert extra == [], ("new top-level files: put site files in web/, scripts in pipeline/, data in "
                         f"data/, docs in docs/ — or add them here on purpose: {extra}")
    import os
    import subprocess
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, env=env, check=True,
                         capture_output=True, text=True).stdout
    dirs = {p.split("/", 1)[0] for p in out.splitlines() if "/" in p}
    assert dirs <= TOP_LEVEL_DIRS, f"new top-level folders: {sorted(dirs - TOP_LEVEL_DIRS)}"


def test_the_site_files_are_in_web():
    for rel in ("index.html", "privacy.html", "terms.html", "sw.js", "manifest.json", "ads.txt",
                "app-ads.txt", "favicon.ico", "apple-touch-icon.png", "og-image.png",
                "static/supercluster/supercluster.min.js", "casa/index.html", "sf/index.html",
                "la/index.html", "dc/index.html", "westchester/index.html", "privacy/index.html",
                "brand/mark.svg", "fonts/oxanium-800.woff2", "nj/rentcontrol.json"):
        assert (ROOT / "web" / rel).is_file(), rel
    for rel in ("data/nj/cgph_links.json", "data/mia/leasing_links.json"):
        assert (ROOT / rel).is_file(), rel


def test_deploy_app_copies_from_web():
    text = (ROOT / "scripts" / "deploy_app.sh").read_text()
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("scp ") and "housing_law_firms" not in s:
            srcs = [t for t in shlex.split(s.split('"$HOST')[0]) if not t.startswith("-")][1:]
            for src in srcs:
                src = src.replace("$c", "sf")
                assert src.startswith("web/"), f"deploy_app.sh copies {src} from outside web/"
                assert (ROOT / src).is_file(), src


def test_builders_read_and_write_the_moved_site_files():
    import importlib
    import sys
    sys.path.insert(0, str(ROOT / "pipeline"))
    bcp = importlib.import_module("build_city_pages")
    assert bcp.SRC == ROOT / "web" / "index.html" and bcp.SRC.is_file()
    for mod, attr, rel in (("build_sf", "OUT", "web/sf/buildings.min.json"),
                           ("build_la", "OUT", "web/la/buildings.min.json"),
                           ("build_dc", "OUT", "web/dc/buildings.min.json")):
        assert getattr(importlib.import_module(mod), attr) == ROOT / rel, mod
    nj = importlib.import_module("scrape_nj_lotteries")
    assert (nj.WEB / "nj" / "rentcontrol.json").is_file() and (nj.DATA / "nj" / "cgph_links.json").is_file()
    assert (importlib.import_module("build_openings").DATA / "mia" / "leasing_links.json").is_file()
