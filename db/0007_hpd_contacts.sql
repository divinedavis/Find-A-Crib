-- Lazy-loaded building operator contacts (the payload split): owner/manager/
-- officer used to be embedded per building in buildings.min.json — 79% of a
-- 39MB file — and are now fetched per building when a popup/detail opens.
-- Public HPD registration data, pre-sanitized by build_hpd_contacts.py
-- (phone numbers stripped to a has_phone flag; real numbers stay in the
-- private agent_phones table behind get_agent_phone()).

create table if not exists public.hpd_contacts (
  bbl     text primary key,
  owner   jsonb,
  manager jsonb,
  officer jsonb
);
alter table public.hpd_contacts enable row level security;
drop policy if exists hpd_contacts_read on public.hpd_contacts;
create policy hpd_contacts_read on public.hpd_contacts for select using (true);
grant select on public.hpd_contacts to anon, authenticated;
grant all on public.hpd_contacts to service_role;
