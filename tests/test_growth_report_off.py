"""The weekly growth report email is off (owner, 2026-11-06: "i dont need this
report anymore"). No cron line may run `growth_run.sh report`, which is what
mails it. The whole engine is paused since 2026-11-07 (owner: "stop the growth
engine"); its run lines stay in the file, commented, ready to resume."""
import pathlib
import re

CRON = pathlib.Path(__file__).resolve().parent.parent / "deploy" / "cron-rentmap-growth"


def _jobs():
    return [l for l in CRON.read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")
            and re.match(r"^[\d*]", l.strip())]


def test_no_job_mails_the_growth_report():
    assert not [l for l in _jobs() if re.search(r"growth_run\.sh\s+report\b", l)]


def test_the_engine_is_paused_with_its_lines_kept():
    text = CRON.read_text()
    assert not [l for l in _jobs() if "growth_run.sh" in l]
    assert "#PAUSED-20261107 0 5 * * * scraper fac-run supabase,smtp,gsc -- /root/Find-A-Crib/pipeline/growth_run.sh daily" in text
    assert "#PAUSED-20261107 40 5 * * * scraper fac-run supabase,smtp,gsc -- /root/Find-A-Crib/pipeline/growth_run.sh build --deploy" in text
