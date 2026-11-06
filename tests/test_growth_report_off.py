"""The weekly growth report email is off (owner, 2026-11-06: "i dont need this
report anymore"). The 05:00 engine run and the 05:40 build stay scheduled; no
cron line may run `growth_run.sh report`, which is what mails it."""
import pathlib
import re

CRON = pathlib.Path(__file__).resolve().parent.parent / "deploy" / "cron-rentmap-growth"


def _jobs():
    return [l for l in CRON.read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")
            and re.match(r"^[\d*]", l.strip())]


def test_no_job_mails_the_growth_report():
    assert not [l for l in _jobs() if re.search(r"growth_run\.sh\s+report\b", l)]


def test_the_engine_itself_still_runs():
    jobs = " ".join(_jobs())
    assert "growth_run.sh daily" in jobs
    assert "growth_run.sh build --deploy" in jobs
