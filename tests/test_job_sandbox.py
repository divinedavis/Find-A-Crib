"""The cron-job sandbox (security audit 2026-10-07, M1/L3/L7).

Every /etc/cron.d/rentmap-* job used to run as root with growth.env and the
API's .env sourced. These pin the contract deploy/install_jobs.sh installs:
no job line runs as root (bar the GeoIP download), each job names its env
sets through fac-run, fac-run loads exactly those, and no address or secret
file reaches a cron line or a log."""
import importlib
import os
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"
CRONS = sorted(DEPLOY.glob("cron-rentmap-*"))
JOB = re.compile(r"^(?:[\d*/,-]+\s+){5}(\S+)\s+(.*)$")


def job_lines():
    for f in CRONS:
        for line in f.read_text().splitlines():
            m = JOB.match(line)
            if m:
                yield f.name, m.group(1), m.group(2)


def env_sets_installed():
    return set(re.findall(r"^mkenv (\S+)", (DEPLOY / "install_jobs.sh").read_text(), re.M))


def test_every_cron_file_has_jobs_or_is_the_paused_one():
    names = {f.name for f in CRONS}
    assert "cron-rentmap-vacancies" in names
    for f in CRONS:
        if f.name != "cron-rentmap-vacancies":
            assert any(n == f.name for n, _, _ in job_lines()), f.name


def test_vacancy_sweep_stays_paused():
    # Owner, 2026-10-06: manager sites' terms forbid scraping.
    assert not [l for n, _, l in job_lines() if n == "cron-rentmap-vacancies"]


def test_no_job_runs_as_root_except_geoip():
    for name, user, cmd in job_lines():
        if user == "root":
            assert name == "cron-rentmap-geoip" and cmd.startswith("/usr/local/sbin/fac-refresh-geoip"), name
        else:
            assert user in ("scraper", "facops"), (name, user)


def test_jobs_go_through_fac_run_with_known_env_sets():
    known = env_sets_installed() | {"none"}
    for name, user, cmd in job_lines():
        if name in ("cron-rentmap-geoip", "cron-rentmap-browser-reaper"):
            continue
        m = re.search(r"fac-run (\S+) -- ", cmd)
        assert m, (name, cmd)
        for e in m.group(1).split(","):
            assert e in known, (name, e)


def test_cron_files_carry_no_secrets_addresses_or_docroot_code():
    for f in CRONS:
        body = "\n".join(l for l in f.read_text().splitlines() if not l.startswith("#"))
        assert "growth.env" not in body and "findacrib-api/.env" not in body, f.name
        assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", body), f.name
        assert "/var/www/rent-map/venv" not in body, f.name
        assert not re.search(r"cd /var/www/rent-map\b", body), f.name
        if re.search(r"^[\d*]", body, re.M) and "fac-run" in body:
            assert re.search(r"^PATH=.*/usr/local/bin", body, re.M), f.name


def test_only_error_report_gets_the_log_reading_user():
    for name, user, _ in job_lines():
        assert (user == "facops") == (name == "cron-rentmap-errors"), name


def _fac_run(env_dir, *args, extra=None):
    env = {"PATH": os.environ["PATH"], "FAC_ENV_DIR": env_dir, "FAC_RUN_ALLOW_ROOT": "1"}
    env.update(extra or {})
    return subprocess.run(["bash", str(DEPLOY / "fac-run"), *args], capture_output=True, text=True, env=env)


def test_fac_run_loads_only_the_named_sets():
    with tempfile.TemporaryDirectory() as d:
        pathlib.Path(d, "a.env").write_text("ALPHA=one\n")
        pathlib.Path(d, "b.env").write_text("BETA='two words'\n")
        r = _fac_run(d, "a", "--", "bash", "-c", 'echo "$ALPHA|${BETA:-unset}|$FAC_ENV_LOADED"')
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "one|unset|1"
        r = _fac_run(d, "a,b", "--", "bash", "-c", 'echo "$ALPHA|$BETA"')
        assert r.stdout.strip() == "one|two words"
        r = _fac_run(d, "none", "--", "bash", "-c", 'echo "${ALPHA:-unset}"')
        assert r.stdout.strip() == "unset"


def test_fac_run_rejects_bad_names_missing_sets_and_bad_usage():
    with tempfile.TemporaryDirectory() as d:
        assert _fac_run(d, "../etc/passwd", "--", "true").returncode == 64
        assert _fac_run(d, "missing", "--", "true").returncode == 66
        assert _fac_run(d, "none", "true").returncode == 64


def test_job_scripts_skip_growth_env_under_fac_run():
    for s in ("lottery_alerts.sh", "saved_alerts.sh", "rerental_daily.sh", "check_rerentals.sh", "growth_run.sh"):
        text = (ROOT / s).read_text()
        for line in text.splitlines():
            if ". ./growth.env" in line and not line.lstrip().startswith("#"):
                assert "FAC_ENV_LOADED" in line, (s, line)


def test_no_script_points_at_the_docroot_venv():
    for p in list(ROOT.glob("*.sh")) + list(ROOT.glob("*.py")) + list((ROOT / "scripts").glob("*.sh")):
        assert "/var/www/rent-map/venv" not in p.read_text(), p.name


def test_deploy_api_never_copies_from_the_box_checkout():
    # The checkout is scraper-writable; root copying code or the systemd
    # drop-in out of it would hand a compromised job the API (or root).
    text = (ROOT / "scripts" / "deploy_api.sh").read_text()
    assert "git pull" not in text
    assert "cp $REPO" not in text and "$REPO/deploy" not in text


def test_section8_feeds_write_to_FAC_DOCROOT(monkeypatch=None):
    sys.path.insert(0, str(ROOT))
    old = os.environ.get("FAC_DOCROOT")
    os.environ["FAC_DOCROOT"] = "/srv/doc"
    try:
        for mod in ("fetch_section8", "scrape_affordablehousing"):
            m = importlib.reload(importlib.import_module(mod))
            assert str(m.OUT) == "/srv/doc/s8.json", mod
            assert str(m.BUILDINGS) == "/srv/doc/buildings.min.json", mod
    finally:
        if old is None:
            os.environ.pop("FAC_DOCROOT", None)
        else:
            os.environ["FAC_DOCROOT"] = old
