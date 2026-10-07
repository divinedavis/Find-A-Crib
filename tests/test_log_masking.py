"""Subscriber addresses stay out of the cron logs (security audit 2026-10-07,
L3: /var/log/rentmap-alerts.log held ~23k full addresses, world-readable)."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_mask_email():
    from growth.emailkit import mask_email
    assert mask_email("jane.doe@gmail.com") == "j***@gmail.com"
    assert mask_email("x@aol.com") == "x***@aol.com"
    assert mask_email("") == ""
    assert mask_email(None) == ""
    assert mask_email("not-an-address") == "***"


def test_alert_logs_never_print_a_full_address():
    for s in ("lottery_alerts.py", "saved_alerts.py", "growth/lifecycle.py", "growth/accounts.py"):
        for i, line in enumerate((ROOT / s).read_text().splitlines(), 1):
            if "print(" in line:
                assert not re.search(r"\{(sub|u|row)\['email'\]\}", line), f"{s}:{i}"
                assert "{args.test_email}" not in line and "{test_email}" not in line, f"{s}:{i}"
