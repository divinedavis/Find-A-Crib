-- Referral-for-Plus: a user shares a single-use link; when a friend signs up
-- through it, BOTH get permanent free Plus. Repeatable — once a link is redeemed
-- the user gets a fresh one. has_plus() only checks for an active subscription
-- row (any plan), so granting Plus = an 'active' subscription with plan='referral'
-- and no period end (permanent). Owner (Stripe) rows are never overwritten.

create extension if not exists pgcrypto;

create table if not exists public.referrals (
  code         text primary key,
  referrer_id  uuid not null references auth.users(id) on delete cascade,
  referred_id  uuid references auth.users(id) on delete set null,
  status       text not null default 'active',   -- 'active' | 'redeemed'
  created_at   timestamptz not null default now(),
  redeemed_at  timestamptz
);
create index if not exists referrals_referrer_idx on public.referrals(referrer_id);
create index if not exists referrals_referred_idx on public.referrals(referred_id);

-- Locked down: only the SECURITY DEFINER RPCs below touch this table.
alter table public.referrals enable row level security;
revoke all on public.referrals from anon, authenticated;

-- Grant permanent Plus to a user without clobbering a real Stripe subscription.
create or replace function public.grant_referral_plus(p_uid uuid)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if public.has_plus(p_uid) then
    return;                       -- already Plus, nothing to do
  end if;
  insert into public.subscriptions (user_id, status, plan, current_period_end)
  values (p_uid, 'active', 'referral', null)
  on conflict (user_id) do update
     set status = 'active', plan = 'referral', current_period_end = null
   where public.subscriptions.stripe_subscription_id is null;  -- never touch paid rows
end;
$$;

-- Return the caller's active share code, minting one if needed.
create or replace function public.get_or_create_referral()
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  uid uuid := auth.uid();
  c   text;
begin
  if uid is null then
    raise exception 'not authenticated';
  end if;
  select code into c from public.referrals
    where referrer_id = uid and status = 'active' limit 1;
  if c is not null then
    return c;
  end if;
  c := lower(substr(replace(gen_random_uuid()::text, '-', ''), 1, 9));
  insert into public.referrals (code, referrer_id) values (c, uid);
  return c;
end;
$$;

-- Redeem a code as the freshly-signed-up user. Grants Plus to both on success.
create or replace function public.redeem_referral(p_code text)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  uid  uuid := auth.uid();
  ref  public.referrals%rowtype;
  born timestamptz;
begin
  if uid is null then
    return jsonb_build_object('ok', false, 'reason', 'not_authenticated');
  end if;
  -- only a brand-new account can redeem (blocks existing users pasting a link)
  select created_at into born from auth.users where id = uid;
  if born is null or born < now() - interval '30 minutes' then
    return jsonb_build_object('ok', false, 'reason', 'not_a_new_signup');
  end if;
  -- a user can only ever be referred once
  if exists (select 1 from public.referrals where referred_id = uid) then
    return jsonb_build_object('ok', false, 'reason', 'already_referred');
  end if;
  select * into ref from public.referrals
    where code = p_code and status = 'active' for update;
  if ref.code is null then
    return jsonb_build_object('ok', false, 'reason', 'invalid_or_used');
  end if;
  if ref.referrer_id = uid then
    return jsonb_build_object('ok', false, 'reason', 'self_referral');
  end if;
  update public.referrals
     set status = 'redeemed', referred_id = uid, redeemed_at = now()
   where code = ref.code and status = 'active';
  perform public.grant_referral_plus(ref.referrer_id);   -- inviter
  perform public.grant_referral_plus(uid);               -- new friend
  return jsonb_build_object('ok', true);
end;
$$;

revoke all on function public.grant_referral_plus(uuid) from public, anon, authenticated;
revoke all on function public.get_or_create_referral() from public;
revoke all on function public.redeem_referral(text) from public;
grant execute on function public.get_or_create_referral() to authenticated;
grant execute on function public.redeem_referral(text) to authenticated;

notify pgrst, 'reload schema';
