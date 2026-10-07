"""events/visits: anonymous inserts may only set the columns the clients send
(security audit 2026-10-07, L12; db/0057). Live check: anon POST with
created_at -> 401, without -> 201."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SQL = (ROOT / "db" / "0057_analytics_insert_columns.sql").read_text()
GRANTS = {t: set(c.replace(" ", "").split(",")) for c, t in
          re.findall(r"grant insert \(([^)]*)\) on public\.(\w+)", SQL)}


def test_no_id_or_created_at():
    for cols in GRANTS.values():
        assert not cols & {"id", "created_at"}


def test_web_and_ios_only_send_granted_columns():
    html = (ROOT / "index.html").read_text()
    for table in ("events", "visits"):
        m = re.search(r"from\('%s'\)\.insert\(\{(.*?)\n\s*\}\)" % table, html, re.S)
        assert m, table
        keys = set(re.findall(r"^\s*(\w+)\s*[:,]", m.group(1), re.M)) - {"platform", "dev", "city", "sid", "touch", "first"}
        top = {k for k in keys if k in {"visitor_id", "user_id", "event", "props", "path", "referrer", "created_at", "id"}}
        assert top <= GRANTS[table], (table, top - GRANTS[table])
    swift = (ROOT / "ios/FindACrib/Services/Analytics.swift").read_text()
    assert '"created_at"' not in swift and '"id":' not in swift


def test_mirrored():
    assert (ROOT / "supabase/migrations/20261007190000_analytics_insert_columns.sql").read_text() == SQL
