"""A chat report's sender field comes from the reporter's phone; the mailed
ban command must name the sender the database stored for that message."""
import io
import json
import os
import contextlib

import chat_reports as cr


def test_ban_command_uses_stored_sender(tmp_path=None):
    real, liar = "aaaaaaaa-0000-0000-0000-000000000001", "bbbbbbbb-0000-0000-0000-000000000002"
    reports = [{"id": 7, "message_id": 41, "bbl": "3002840015", "reporter": "r", "sender": liar,
                "plaintext": "hi", "reason": "spam", "created_at": "2026-10-18T10:00:00Z"},
               {"id": 8, "message_id": 99, "bbl": "3002840015", "reporter": "r", "sender": liar,
                "plaintext": "x", "reason": "spam", "created_at": "2026-10-18T10:00:00Z"}]

    def fake_rest(method, path, body=None, prefer=None):
        if path.startswith("chat_reports"):
            return reports
        assert path.startswith("chat_messages") and "in.%2841%2C99%29" in path, path
        return [{"id": 41, "sender": real, "bbl": "3002840015"}]   # 99 was deleted

    old, cr.rest = cr.rest, fake_rest
    os.environ["CHAT_REPORT_STATE"] = "/nonexistent/state.json"
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cr.mail_new(dry=True)
    finally:
        cr.rest = old
    text = out.getvalue()
    assert f"--ban {real}" in text and f"--ban {liar}" not in text, text
    assert "WARNING" in text and "already gone" in text, text
