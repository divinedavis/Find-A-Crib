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
