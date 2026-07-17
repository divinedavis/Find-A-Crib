-- Developer portal: self-serve key creation, status lookup, and tier changes
-- driven by the Stripe webhook. All service-role only (called by api_server.py).

-- Self-serve signup. One active FREE key per email: re-signing up rotates it
-- (old free key revoked, new one issued). If the email already has a PAID key,
-- refuse — they should manage it in the dashboard, not mint a new free one.
create or replace function public.api_create_key(p_email text, p_key_hash text, p_key_prefix text)
returns jsonb language plpgsql security definer set search_path = public as $$
begin
  if exists (select 1 from api_keys where owner_email = p_email
             and status = 'active' and tier in ('pro', 'business')) then
    return jsonb_build_object('ok', false, 'reason', 'has_paid_key');
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

-- Dashboard status for a key (does NOT count as a metered request).
create or replace function public.api_key_status(p_key_hash text)
returns jsonb language sql security definer set search_path = public as $$
  select case when k.id is null then jsonb_build_object('ok', false)
    else jsonb_build_object('ok', true, 'id', k.id, 'tier', k.tier,
      'owner', k.owner_email, 'prefix', k.key_prefix, 'status', k.status,
      'limit', api_tier_limit(k.tier),
      'used_today', coalesce((select count from api_usage u where u.key_id = k.id and u.day = current_date), 0),
      'paid', k.tier in ('pro','business'))
  end
  from (select * from api_keys where key_hash = p_key_hash) k
  right join (select 1) _ on true;
$$;
revoke all on function public.api_key_status(text) from public, anon, authenticated;
grant execute on function public.api_key_status(text) to service_role;

-- Called by the Stripe webhook to apply a paid tier to a key.
create or replace function public.api_set_tier(p_key_id uuid, p_tier text, p_customer text, p_sub text)
returns void language sql security definer set search_path = public as $$
  update api_keys set tier = p_tier, stripe_customer_id = p_customer,
    stripe_subscription_id = p_sub, status = 'active'
  where id = p_key_id;
$$;
revoke all on function public.api_set_tier(uuid, text, text, text) from public, anon, authenticated;
grant execute on function public.api_set_tier(uuid, text, text, text) to service_role;

-- Called by the webhook on subscription cancellation → back to free.
create or replace function public.api_downgrade_by_sub(p_sub text)
returns void language sql security definer set search_path = public as $$
  update api_keys set tier = 'free', stripe_subscription_id = null
  where stripe_subscription_id = p_sub;
$$;
revoke all on function public.api_downgrade_by_sub(text) from public, anon, authenticated;
grant execute on function public.api_downgrade_by_sub(text) to service_role;
