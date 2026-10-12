-- Agent phone numbers are a paid feature (owner, 2026-10-12: "make agents
-- phone number a paid feature"). get_agent_phone() answered any signed-in
-- account while everything-free mode is on (has_features = signed in); it
-- now answers only Find A Crib Plus (has_plus: paying, trialing or comped).
-- The managing agent's and owner's NAMES stay free with an account.
create or replace function public.get_agent_phone(p_bbl text)
returns text
language sql
stable
security definer
set search_path = public
as $$
  select case when public.has_plus(auth.uid())
              then (select phone from public.agent_phones where bbl = p_bbl)
              else null end;
$$;
