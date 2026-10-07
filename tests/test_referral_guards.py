"""Referral farming guards (security audit 2026-10-07, M2; db/0055).

The behaviour itself is exercised against the live database by
tests/sql/referral_guards_test.sql (rollback-only; needs the Supabase PAT,
so it is not part of CI). Its 2026-10-07 run:
  same_ip=same_network r1..r3=ok r4=referrer_limit a6=rate_limited
These pin the migration's contract so a later CREATE OR REPLACE that drops a
guard fails here first."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SQL = (ROOT / "db" / "0055_referral_abuse_guards.sql").read_text()


def _redeem_body():
    return SQL.split("create or replace function public.redeem_referral", 1)[1].split("$$;", 1)[0]


def test_mirrored_into_supabase_migrations():
    assert (ROOT / "supabase" / "migrations" / "20261007170000_referral_abuse_guards.sql").read_text() == SQL


def test_redeem_keeps_every_guard_before_any_grant():
    body = _redeem_body()
    grant = body.index("grant_referral_plus")
    for reason in ("rate_limited", "not_a_new_signup", "already_referred", "self_referral",
                   "same_network", "referrer_limit"):
        assert f"'{reason}'" in body, reason
        assert body.index(f"'{reason}'") < grant, reason


def test_caps_are_3_a_month_and_10_ever():
    body = _redeem_body()
    assert re.search(r"interval '30 days'\) >= 3", body)
    assert re.search(r"status = 'redeemed'\) >= 10", body)


def test_ips_are_only_stored_salted_and_hashed_and_private():
    assert "extensions.digest(" in SQL and "private.app_salt" in SQL
    assert "revoke all on schema private from public, anon, authenticated" in SQL
    assert "revoke all on function public.redeem_referral(text) from public, anon" in SQL
    assert not re.search(r"insert into private\.referral_ip_log \([^)]*\bip\b[^_]", SQL)
