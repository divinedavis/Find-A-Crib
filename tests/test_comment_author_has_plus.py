"""Comment author integrity + has_plus() scope (security audit 2026-10-07, L2;
db/0056). Behaviour checked live by tests/sql/comment_author_has_plus_test.sql
(rollback-only, needs the PAT): nested_postgres=true other_uid=false
own_uid=false author=zed.tester self_plus=true service_role=true."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SQL = (ROOT / "db" / "0056_comment_author_and_has_plus_scope.sql").read_text()


def test_mirrored_into_supabase_migrations():
    assert (ROOT / "supabase" / "migrations" / "20261007180000_comment_author_and_has_plus_scope.sql").read_text() == SQL


def test_has_plus_is_invoker_and_refuses_other_uids():
    body = SQL.split("create or replace function public.has_plus", 1)[1].split("$$;", 1)[0]
    assert "security invoker" in body
    assert re.search(r"current_user in \('anon', 'authenticated'\) and uid is distinct from auth\.uid\(\) then false", body)
    assert "revoke all on function public.has_plus(uuid) from public, anon" in SQL


def test_author_is_set_by_trigger_from_the_account():
    assert "before insert or update of author, user_id on public.building_comments" in SQL
    body = SQL.split("create or replace function public.set_comment_author", 1)[1].split("$$;", 1)[0]
    assert "new.author := left(n, 60)" in body and "auth.users" in body


def test_clients_still_select_user_id_so_it_is_not_revoked():
    # Revoking anon SELECT on user_id would fail these queries outright.
    assert "user_id" in (ROOT / "ios/FindACrib/Services/CommentsStore.swift").read_text()
    assert not re.search(r"revoke\s+select\s*\(\s*user_id", SQL, re.I)
