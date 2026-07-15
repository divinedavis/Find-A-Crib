-- Research (Plus feature): how many buildings/apartments a landlord owns or a
-- managing agent represents, citywide and per borough, with violation totals.
--
-- research_names:      bbl -> normalized owner/agent name keys.
-- research_portfolios: one row per (kind, name) with precomputed aggregates.
-- Both are PRIVATE (RLS on, no anon/authenticated policies) and written only
-- by build_research.py via the service role, same pattern as agent_phones.
-- The only user-facing surface is get_research(), which requires Plus.

create table if not exists public.research_names (
  bbl       text primary key,
  owner_key text,
  agent_key text
);
alter table public.research_names enable row level security;
revoke all on public.research_names from anon, authenticated;
grant all on public.research_names to service_role;

create table if not exists public.research_portfolios (
  kind            text not null check (kind in ('owner','agent')),
  key             text not null,
  display_name    text not null,
  buildings       int  not null,
  units           int  not null,
  by_boro         jsonb not null,
  open_violations int  not null default 0,
  open_complaints int  not null default 0,
  class_c         int  not null default 0,
  updated_at      timestamptz not null default now(),
  primary key (kind, key)
);
alter table public.research_portfolios enable row level security;
revoke all on public.research_portfolios from anon, authenticated;
grant all on public.research_portfolios to service_role;

create or replace function public.get_research(p_bbl text)
returns jsonb language sql stable security definer set search_path = public as $$
  select case when public.has_plus(auth.uid()) then
    jsonb_build_object(
      'owner', (select to_jsonb(p) - 'key' - 'kind'
                from research_portfolios p
                join research_names n on p.kind = 'owner' and n.owner_key = p.key
                where n.bbl = p_bbl),
      'agent', (select to_jsonb(p) - 'key' - 'kind'
                from research_portfolios p
                join research_names n on p.kind = 'agent' and n.agent_key = p.key
                where n.bbl = p_bbl))
  else null end;
$$;
revoke all on function public.get_research(text) from public;
grant execute on function public.get_research(text) to authenticated;
