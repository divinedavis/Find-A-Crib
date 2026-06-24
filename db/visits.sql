-- Anonymous returning-visitor analytics for Find A Crib (findacrib.com).
-- A first-party visitor_id (browser localStorage 'fac_vid') is pinged once per
-- page load from index.html; user_id is attached when the visitor is signed in.
-- Privacy: no IP stored. RLS lets anyone INSERT but no one SELECT except service_role.
create table if not exists public.visits (
  id          bigint generated always as identity primary key,
  visitor_id  text not null,
  user_id     uuid references auth.users(id) on delete set null,
  path        text,
  referrer    text,
  created_at  timestamptz not null default now()
);
create index if not exists visits_visitor_created_idx on public.visits (visitor_id, created_at);
create index if not exists visits_created_idx on public.visits (created_at);
create index if not exists visits_user_idx on public.visits (user_id) where user_id is not null;

alter table public.visits enable row level security;

drop policy if exists visits_insert on public.visits;
create policy visits_insert on public.visits
  for insert to anon, authenticated
  with check ( user_id is null or user_id = auth.uid() );  -- can't spoof another user's id

grant insert on public.visits to anon, authenticated;
grant all    on public.visits to service_role;
