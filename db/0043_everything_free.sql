-- 2026-10-01 (owner): "make everything free in the app and website for now".
-- Every Plus feature (agent phone numbers, lottery-agent contacts, landlord
-- research, saved searches, folders) opens to any signed-in account. Ads and
-- no-ads are untouched: has_plus() still means "pays", and decides no-ads.
--
-- ONE switch: has_features(). To bring paid gating back, change its body to
--   select public.has_plus(uid);
-- and nothing else.

create or replace function public.has_features(uid uuid)
returns boolean
language sql
stable
security definer
set search_path to 'public'
as $$ select uid is not null; $$;
revoke all on function public.has_features(uuid) from public, anon;
grant execute on function public.has_features(uuid) to authenticated, service_role;

CREATE OR REPLACE FUNCTION public.get_agent_phone(p_bbl text)
 RETURNS text
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select case when public.has_features(auth.uid())
              then (select phone from public.agent_phones where bbl = p_bbl)
              else null end;
$function$;

CREATE OR REPLACE FUNCTION public.get_lottery_agent_contacts()
 RETURNS jsonb
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select case when public.has_features(auth.uid()) then
    coalesce((select jsonb_object_agg(c.key, to_jsonb(c) - 'key' - 'updated_at')
              from public.lottery_agent_contacts c), '{}'::jsonb)
  else null end;
$function$;

CREATE OR REPLACE FUNCTION public.get_research(p_bbl text)
 RETURNS jsonb
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select case when public.has_features(auth.uid()) then
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
$function$;

CREATE OR REPLACE FUNCTION public.get_research_bbls(p_kind text, p_key text)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_kind text := case when p_kind = 'owner' then 'owner' else 'agent' end;
  v_key  text := nullif(btrim(coalesce(p_key, '')), '');
  v_name text;
  v_bbls jsonb;
begin
  if not public.has_features(auth.uid()) or v_key is null then
    return null;
  end if;

  -- Exact key match, never a pattern: the caller is naming a row it already
  -- has, so there is nothing to search and no wildcard to escape.
  select p.display_name into v_name
  from public.research_portfolios p
  where p.kind = v_kind and p.key = v_key;

  if v_name is null then
    return null;
  end if;

  -- The largest portfolio in the data is 259 buildings, so the cap is headroom
  -- rather than a limit anyone will meet; it is here so a future data import
  -- cannot turn one click into a megabyte.
  select coalesce(jsonb_agg(b.bbl), '[]'::jsonb) into v_bbls
  from (
    select n.bbl from public.research_names n
    where (case when v_kind = 'owner' then n.owner_key else n.agent_key end) = v_key
    order by n.bbl
    limit 2000
  ) b;

  return jsonb_build_object('kind', v_kind, 'key', v_key,
                            'display_name', v_name, 'bbls', v_bbls);
end;
$function$;

CREATE OR REPLACE FUNCTION public.get_research_directory(p_kind text DEFAULT 'agent'::text, p_q text DEFAULT NULL::text, p_boro text DEFAULT NULL::text, p_nb text DEFAULT NULL::text, p_sort text DEFAULT 'buildings'::text, p_limit integer DEFAULT 50, p_offset integer DEFAULT 0)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
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
  if not public.has_features(auth.uid()) then
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
$function$;

CREATE OR REPLACE FUNCTION public.get_research_places()
 RETURNS jsonb
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select case when public.has_features(auth.uid()) then
    coalesce((select jsonb_agg(jsonb_build_object('boro', boro, 'nb', nb) order by boro, nb)
              from (select distinct boro, nb from public.research_names
                    where boro is not null and nb is not null) p), '[]'::jsonb)
  else null end;
$function$;

drop policy if exists cat_insert_plus on public.categories;
create policy cat_insert_plus on public.categories for insert
  with check ((auth.uid() = user_id) and public.has_features(auth.uid()));

drop policy if exists ss_insert_plus on public.saved_searches;
create policy ss_insert_plus on public.saved_searches for insert
  with check ((auth.uid() = user_id) and public.has_features(auth.uid()));

notify pgrst, 'reload schema';
