-- The buildings behind one directory row, so clicking a name in /directory/
-- opens the map on exactly that portfolio.
--
-- The map already knows how to do this: type a landlord's name and the search
-- falls through to an "org" tier that filters to their buildings, lists them
-- and frames the map on their bounds. What it does NOT do is agree with the
-- directory. That tier substring-matches hpd_contacts.names, so searching
-- "SHINDA MANAGEMENT CORP" also sweeps in "SHINDA MANAGEMENT CORPORATION" and
-- the map shows a different count from the row that was clicked. Both numbers
-- look authoritative and one of them is wrong.
--
-- research_names already holds the exact normalized key per bbl — the same key
-- the row was aggregated from — so this returns the portfolio itself rather
-- than everything whose name contains it.

create index if not exists research_names_agent_key_idx on public.research_names (agent_key);
create index if not exists research_names_owner_key_idx on public.research_names (owner_key);

create or replace function public.get_research_bbls(p_kind text, p_key text)
returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
  v_kind text := case when p_kind = 'owner' then 'owner' else 'agent' end;
  v_key  text := nullif(btrim(coalesce(p_key, '')), '');
  v_name text;
  v_bbls jsonb;
begin
  if not public.has_plus(auth.uid()) or v_key is null then
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
$$;
revoke all on function public.get_research_bbls(text, text) from public, anon, authenticated;
grant execute on function public.get_research_bbls(text, text) to authenticated;
