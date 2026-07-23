-- Anti-automation for self-serve key creation (issue #20).
--
-- api_create_key rotated the FREE key on every re-signup (revoke old, issue
-- new) with no ceiling, so one email could mint unlimited 1000-req/day keys and
-- bloat api_keys. Keep rotation (a lost key can be re-issued) but cap the number
-- of free keys an email can create per day. Paid keys still 409 (has_paid_key).
-- Pairs with the per-IP rate limit on /developers/signup in api_server.py.

create or replace function public.api_create_key(p_email text, p_key_hash text, p_key_prefix text)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  free_today int;
begin
  if exists (select 1 from api_keys where owner_email = p_email
             and status = 'active' and tier in ('pro', 'business')) then
    return jsonb_build_object('ok', false, 'reason', 'has_paid_key');
  end if;
  select count(*) into free_today from api_keys
    where owner_email = p_email and tier = 'free' and created_at >= current_date;
  if free_today >= 5 then
    return jsonb_build_object('ok', false, 'reason', 'free_key_limit');
  end if;
  update api_keys set status = 'revoked'
    where owner_email = p_email and status = 'active' and tier = 'free';
  insert into api_keys (key_hash, key_prefix, owner_email, tier)
    values (p_key_hash, p_key_prefix, p_email, 'free');
  return jsonb_build_object('ok', true, 'tier', 'free');
end;
$$;
revoke all on function public.api_create_key(text, text, text) from public, anon, authenticated;
grant execute on function public.api_create_key(text, text, text) to service_role;
