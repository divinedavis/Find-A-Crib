-- Owner / managing-agent / head-officer contacts require a signed-in account.
--
-- WHAT WAS ACTUALLY EXPOSED
-- -------------------------
-- The earlier migration granted `select` on this table to `anon`, which is the
-- role the browser's publishable key runs as -- and that key ships in
-- /config.js, in the clear, to everyone. So this was not "visible in the UI to
-- logged-out users"; it was a public bulk endpoint over 46,694 rows. Verified
-- before this change, with nothing but the key off the live site:
--
--   GET /rest/v1/hpd_contacts?select=bbl,names&limit=2
--   [{"bbl":"1007220003","names":"new 41st street realty holdings co. llc |
--     lewis rosenthal | robert krueger"}, ...]
--
-- Named individuals -- head officers are people, not companies -- keyed to a
-- building address, downloadable in bulk by anyone who viewed source. Hiding
-- the panel in index.html would have left that endpoint exactly as it was, so
-- the grant is the fix and the UI change merely follows it.
--
-- `anon` and `public` are revoked separately on purpose: revoking from PUBLIC
-- does not remove a grant held directly by a named role, and this project has
-- been bitten by that distinction before.
revoke select on public.hpd_contacts from anon;
revoke select on public.hpd_contacts from public;

-- Signed-in users keep it. service_role bypasses RLS and grants entirely, so
-- the API server and the build scripts are unaffected.
grant select on public.hpd_contacts to authenticated;

-- RLS as the second lock. Grants alone decide PostgREST visibility today, but a
-- future `grant select ... to anon` -- the exact line this migration undoes --
-- would silently re-open the table. With RLS on and only an authenticated
-- policy, that mistake fails closed instead.
alter table public.hpd_contacts enable row level security;

drop policy if exists hpd_contacts_read_authenticated on public.hpd_contacts;
create policy hpd_contacts_read_authenticated
  on public.hpd_contacts
  for select
  to authenticated
  using (true);

-- No insert/update/delete policy for anyone: the table is written by the build
-- scripts under service_role, which RLS does not apply to.
