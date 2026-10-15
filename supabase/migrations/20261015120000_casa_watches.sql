-- Your Casa (owner, 2026-10-15): a Plus member picks one building and hears
-- about every new 311 call on it. One row per account — "a building of their
-- choice". Written only by api_server.py (/casa/watch, service role) after it
-- has verified the session and has_plus(); read by casa_alerts.py, which
-- advances last_seen to the newest 311 created_date it has announced.
create table if not exists public.casa_watches (
  user_id    uuid primary key references auth.users (id) on delete cascade,
  email      text not null,
  bbl        text not null check (bbl ~ '^[1-5][0-9]{9}$'),
  address    text not null default '',
  created_at timestamptz not null default now(),
  last_seen  timestamptz,
  last_sent  timestamptz
);
create index if not exists casa_watches_bbl on public.casa_watches (bbl);

alter table public.casa_watches enable row level security;

-- App convention (memory: anon default grants): grant select and let RLS
-- deny. A signed-in user can read only their own row; nobody but the service
-- role writes.
revoke insert, update, delete, truncate, trigger, references on public.casa_watches from anon, authenticated;
grant select on public.casa_watches to anon, authenticated;
grant all on public.casa_watches to service_role;

drop policy if exists casa_watches_own_read on public.casa_watches;
create policy casa_watches_own_read on public.casa_watches
  for select to authenticated using (auth.uid() = user_id);

notify pgrst, 'reload schema';
