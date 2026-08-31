-- Two Plus-gated surfaces that share one idea: the data a subscriber pays for
-- must never sit in a file nginx will hand to anybody who asks.
--
-- 1. lottery_agent_contacts — the contact block and re-rental listing URL for
--    each firm on HPD's Pre-Qualified List. These used to ride along in the
--    public /marketing_agents.json, so "gating" them in the page would have
--    been theatre: the JSON is one fetch away. They now live here, private,
--    and reach the browser only through get_lottery_agent_contacts().
--
-- 2. get_research_directory() — the owner/managing-agent table. The rows
--    already exist in research_portfolios (built by build_research.py) and are
--    already private; what is new is a LIST query shape. get_research(p_bbl)
--    answers "who runs this building"; this answers "show me every agent in
--    Bed-Stuy, biggest portfolio first".
--
-- Both follow the house pattern from 0004: private table, no anon/authenticated
-- grants at all, one SECURITY DEFINER function that checks has_plus() and
-- returns null (not an error) to everyone else.

-- ---------------------------------------------------------------- contacts --
create table if not exists public.lottery_agent_contacts (
  key            text primary key,          -- normalized firm name, matches marketing_agents.json
  display_name   text not null,
  contact        text,
  email          text,
  phone          text,
  address        text,
  website        text,
  rerental_url   text,
  rerental_title text,
  rerental_note  text,
  updated_at     timestamptz not null default now()
);
alter table public.lottery_agent_contacts enable row level security;
-- No policies and no grants: nothing reaches this table except the service role
-- (the nightly push) and the definer function below, which runs as the owner.
revoke all on public.lottery_agent_contacts from anon, authenticated;
grant all on public.lottery_agent_contacts to service_role;

-- One call returns the whole block — 85 firms is a few KB, and paging it would
-- only add round trips to a table the subscriber is entitled to all of.
create or replace function public.get_lottery_agent_contacts()
returns jsonb language sql stable security definer set search_path = public as $$
  select case when public.has_plus(auth.uid()) then
    coalesce((select jsonb_object_agg(c.key, to_jsonb(c) - 'key' - 'updated_at')
              from public.lottery_agent_contacts c), '{}'::jsonb)
  else null end;
$$;
-- Supabase grants EXECUTE on every new public function to anon AND authenticated
-- by name; revoking from `public` alone leaves the anon grant in place and the
-- function callable with just the publishable key. Name the roles.
revoke all on function public.get_lottery_agent_contacts() from public, anon, authenticated;
grant execute on function public.get_lottery_agent_contacts() to authenticated;

-- --------------------------------------------------------------- directory --
-- Where each building sits, so the directory can filter by borough and
-- neighborhood. research_names is bbl -> owner/agent key; these two columns
-- make it bbl -> owner/agent key + place, which is all a filter needs.
alter table public.research_names add column if not exists boro text;
alter table public.research_names add column if not exists nb   text;

-- Filter shape is "every building this firm has in <neighborhood>", so the
-- lookup runs name-key-first from a neighborhood, not the other way round.
create index if not exists research_names_nb_agent_idx on public.research_names (nb, agent_key);
create index if not exists research_names_nb_owner_idx on public.research_names (nb, owner_key);
create index if not exists research_names_boro_idx     on public.research_names (boro);

-- Default sort is portfolio size within a kind.
create index if not exists research_portfolios_kind_buildings_idx
  on public.research_portfolios (kind, buildings desc);
-- by_boro is a jsonb object keyed by borough, so the borough filter is a `?`
-- containment test rather than a join back to research_names.
create index if not exists research_portfolios_by_boro_idx
  on public.research_portfolios using gin (by_boro jsonb_path_ops);

-- Name search is a substring match on 60k rows; without trigrams the leading
-- wildcard makes it a sequential scan on every keystroke.
create extension if not exists pg_trgm;
create index if not exists research_portfolios_name_trgm_idx
  on public.research_portfolios using gin (display_name gin_trgm_ops);

create or replace function public.get_research_directory(
  p_kind   text default 'agent',
  p_q      text default null,
  p_boro   text default null,
  p_nb     text default null,
  p_sort   text default 'buildings',
  p_limit  int  default 50,
  p_offset int  default 0)
returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
  -- Every argument is clamped or whitelisted before it reaches a query. The
  -- caller is a paying subscriber, not a trusted one.
  v_kind   text := case when p_kind = 'owner' then 'owner' else 'agent' end;
  v_sort   text := case when p_sort in ('buildings','units','violations','name')
                        then p_sort else 'buildings' end;
  v_limit  int  := least(greatest(coalesce(p_limit, 50), 1), 100);
  v_offset int  := least(greatest(coalesce(p_offset, 0), 0), 100000);
  v_boro   text := nullif(btrim(coalesce(p_boro, '')), '');
  v_nb     text := nullif(btrim(coalesce(p_nb, '')), '');
  v_q      text := nullif(btrim(coalesce(p_q, '')), '');
  v_total  bigint;
  v_rows   jsonb;
begin
  if not public.has_plus(auth.uid()) then
    return null;
  end if;

  -- A bare "%" would otherwise match every row and page through the whole
  -- table; escaping the metacharacters keeps a search a search.
  if v_q is not null then
    v_q := '%' || replace(replace(replace(v_q, '\', '\\'), '%', '\%'), '_', '\_') || '%';
  end if;

  -- Count and page are two queries on purpose. Ranking the whole match set
  -- just to slice it in JSON would materialise 21,000 rows to return 50; this
  -- lets the (kind, buildings desc) and trigram indexes do the work.
  select count(*) into v_total
  from public.research_portfolios p
  where p.kind = v_kind
    and (v_q    is null or p.display_name ilike v_q escape '\')
    and (v_boro is null or p.by_boro ? v_boro)
    and (v_nb   is null or exists (
           select 1 from public.research_names n
           where n.nb = v_nb
             and (case when v_kind = 'owner' then n.owner_key else n.agent_key end) = p.key));

  select coalesce(jsonb_agg(to_jsonb(r) order by r.ord), '[]'::jsonb) into v_rows
  from (
    select p.key, p.display_name, p.buildings, p.units, p.by_boro,
           p.open_violations, p.open_complaints, p.class_c,
           row_number() over () as ord
    from public.research_portfolios p
    where p.kind = v_kind
      and (v_q    is null or p.display_name ilike v_q escape '\')
      and (v_boro is null or p.by_boro ? v_boro)
      and (v_nb   is null or exists (
             select 1 from public.research_names n
             where n.nb = v_nb
               and (case when v_kind = 'owner' then n.owner_key else n.agent_key end) = p.key))
    order by case when v_sort = 'buildings'  then p.buildings       end desc nulls last,
             case when v_sort = 'units'      then p.units           end desc nulls last,
             case when v_sort = 'violations' then p.open_violations end desc nulls last,
             case when v_sort = 'name'       then p.display_name    end asc  nulls last,
             p.display_name asc
    limit v_limit offset v_offset
  ) r;

  return jsonb_build_object(
    'kind',   v_kind,
    'sort',   v_sort,
    'total',  v_total,
    'limit',  v_limit,
    'offset', v_offset,
    'rows',   (select coalesce(jsonb_agg(e - 'ord'), '[]'::jsonb)
               from jsonb_array_elements(v_rows) e));
end;
$$;
revoke all on function public.get_research_directory(text,text,text,text,text,int,int)
  from public, anon, authenticated;
grant execute on function public.get_research_directory(text,text,text,text,text,int,int)
  to authenticated;

-- The borough/neighborhood picker. Public knowledge on its own, but it is only
-- ever drawn on a page a subscriber is already looking at, so it carries the
-- same gate rather than opening a second, softer door onto research_names.
create or replace function public.get_research_places()
returns jsonb language sql stable security definer set search_path = public as $$
  select case when public.has_plus(auth.uid()) then
    coalesce((select jsonb_agg(jsonb_build_object('boro', boro, 'nb', nb) order by boro, nb)
              from (select distinct boro, nb from public.research_names
                    where boro is not null and nb is not null) p), '[]'::jsonb)
  else null end;
$$;
revoke all on function public.get_research_places() from public, anon, authenticated;
grant execute on function public.get_research_places() to authenticated;
