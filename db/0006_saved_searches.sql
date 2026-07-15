-- Saved searches (Plus): the whole search state (query, boroughs,
-- neighborhoods, listed/S8/beds/violations filters, map view) as jsonb,
-- reapplied from the profile. INSERT requires an active subscription, same
-- hard gate as saved_buildings.

create table if not exists public.saved_searches (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  name       text not null,
  params     jsonb not null,
  created_at timestamptz not null default now()
);
alter table public.saved_searches enable row level security;

drop policy if exists ss_select_own on public.saved_searches;
drop policy if exists ss_insert_plus on public.saved_searches;
drop policy if exists ss_delete_own on public.saved_searches;
create policy ss_select_own on public.saved_searches
  for select using (auth.uid() = user_id);
create policy ss_insert_plus on public.saved_searches
  for insert with check (auth.uid() = user_id and public.has_plus(auth.uid()));
create policy ss_delete_own on public.saved_searches
  for delete using (auth.uid() = user_id);

grant select, insert, delete on public.saved_searches to authenticated;
grant all on public.saved_searches to service_role;
