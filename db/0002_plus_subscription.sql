-- Find A Crib Plus: $1.99/mo subscription that unlocks BOTH managing-agent phone
-- numbers and like-categories. Phones are PRIVATE (never in the public JSON);
-- they are only reachable through get_agent_phone(), which checks for an active
-- subscription server-side. Categories are gated at insert time the same way.

-- 1. Subscriptions — written ONLY by the Stripe webhook (service_role).
create table if not exists public.subscriptions (
  user_id                uuid primary key references auth.users(id) on delete cascade,
  stripe_customer_id     text,
  stripe_subscription_id text,
  status                 text not null default 'inactive',  -- active|trialing|past_due|canceled|inactive
  plan                   text not null default 'plus',
  current_period_end     timestamptz,
  updated_at             timestamptz not null default now()
);
alter table public.subscriptions enable row level security;
drop policy if exists sub_select_own on public.subscriptions;
create policy sub_select_own on public.subscriptions for select using (auth.uid() = user_id);

-- 2. Agent phones — PRIVATE table. RLS is on with NO anon/authenticated policy,
--    so direct reads are denied; access is only via the definer function below.
create table if not exists public.agent_phones (
  bbl        text primary key,
  phone      text not null,
  agent_name text,
  confidence numeric,
  updated_at timestamptz not null default now()
);
alter table public.agent_phones enable row level security;

-- 3. Entitlement check.
create or replace function public.has_plus(uid uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.subscriptions s
    where s.user_id = uid
      and s.status in ('active','trialing')
      and (s.current_period_end is null or s.current_period_end > now())
  );
$$;

-- 4. Gated phone lookup — returns the number ONLY for paying users, else null.
create or replace function public.get_agent_phone(p_bbl text)
returns text language sql stable security definer set search_path = public as $$
  select case when public.has_plus(auth.uid())
              then (select phone from public.agent_phones where bbl = p_bbl)
              else null end;
$$;

-- 5. Like categories — Plus-gated to create; user owns their own rows.
create table if not exists public.categories (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  name       text not null,
  color      text,
  created_at timestamptz not null default now(),
  unique (user_id, name)
);
alter table public.categories enable row level security;
drop policy if exists cat_select_own on public.categories;
drop policy if exists cat_insert_plus on public.categories;
drop policy if exists cat_update_own on public.categories;
drop policy if exists cat_delete_own on public.categories;
create policy cat_select_own  on public.categories for select using (auth.uid() = user_id);
create policy cat_insert_plus on public.categories for insert with check (auth.uid() = user_id and public.has_plus(auth.uid()));
create policy cat_update_own  on public.categories for update using (auth.uid() = user_id);
create policy cat_delete_own  on public.categories for delete using (auth.uid() = user_id);

-- assign a saved building to one of the user's categories
alter table public.saved_buildings add column if not exists category_id uuid references public.categories(id) on delete set null;
drop policy if exists own_update on public.saved_buildings;
create policy own_update on public.saved_buildings for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- 6. Grants (Data API requires explicit grants).
grant select on public.subscriptions to authenticated;
grant select, insert, update, delete on public.categories to authenticated;
grant update on public.saved_buildings to authenticated;
grant all on public.subscriptions to service_role;
grant all on public.agent_phones  to service_role;
grant all on public.categories    to service_role;
-- definer funcs: anon callers simply get null (auth.uid() is null -> has_plus false)
grant execute on function public.has_plus(uuid)        to anon, authenticated;
grant execute on function public.get_agent_phone(text) to anon, authenticated;
