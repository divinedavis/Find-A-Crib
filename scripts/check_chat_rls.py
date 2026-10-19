#!/usr/bin/env python3
"""Building chat RLS, checked on the live database the way the app writes.

PostgREST wraps every insert in `... RETURNING`, so a new row must also pass
the table's SELECT policy. Build 144's first join failed on exactly that
(db/0064), and a check that inserted without RETURNING passed 11/11 anyway.
Every statement here runs as an `authenticated` user inside a transaction
that is rolled back, so nothing is left behind.

    python3 scripts/check_chat_rls.py      # PAT from keychain supabase-pat-clockin

Run it after any migration that touches chat_* tables or policies.
"""
import json, subprocess, sys, urllib.error, urllib.request

REF = "dbaifotzwlxjvsxjohjt"
OWNER = "af2629f7-1121-4bee-8a2b-cede9318c864"     # a real account; rows are rolled back
STRANGER = "33333333-0000-0000-0000-000000000000"
BBL = "3019150068"


def query(token, sql):
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{REF}/database/query",
        data=json.dumps({"query": sql}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "curl/8.7.1"})          # Cloudflare 403s urllib's default
    try:
        return True, json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        return False, e.read().decode()


def as_user(uid, *stmts):
    claims = json.dumps({"sub": uid, "role": "authenticated"})
    return ("begin; set local role authenticated; "
            f"select set_config('request.jwt.claims', '{claims}', true); "
            + " ".join(stmts) + " rollback;")


JOIN = (f"insert into public.chat_members(bbl, user_id, agreed_terms_at) "
        f"values ('{BBL}', '{OWNER}', now()) on conflict do nothing returning bbl;")
POST = (f"insert into public.chat_messages(bbl, salt, ciphertext, keys) values "
        f"('{BBL}', 'c2FsdHNhbHRzYWx0c2FsdA==', 'Y2lwaGVy', '{{\"{OWNER}\": \"a2V5\"}}'::jsonb) returning id;")
CASES = [
    ("join with RETURNING", True, as_user(OWNER, JOIN)),
    ("post after joining", True, as_user(OWNER, JOIN, POST)),
    ("post without joining", False, as_user(OWNER, POST)),
    ("join as someone else", False, as_user(OWNER, JOIN.replace(f"'{OWNER}', now()", f"'{STRANGER}', now()"))),
    ("non-member can't list members", True,
     as_user(OWNER, "select count(*) as n from public.chat_members where user_id <> auth.uid();")),
]


def main():
    token = subprocess.check_output(["security", "find-generic-password", "-s",
                                     "supabase-pat-clockin", "-w"]).decode().strip()
    failed = 0
    for name, want_ok, sql in CASES:
        ok, out = query(token, sql)
        good = ok == want_ok
        if good and name.startswith("non-member"):
            good = out[-1].get("n") == 0
        failed += not good
        print(("PASS " if good else "FAIL ") + name + ("" if good else f": {str(out)[:200]}"))
    ok, out = query(token, f"select (select count(*) from chat_members where user_id = '{OWNER}') "
                           f"+ (select count(*) from chat_messages where sender = '{OWNER}') as n")
    if not ok or out[0]["n"] != 0:
        print(f"note: the owner has real chat rows now ({out}); the checks still rolled back their own")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
