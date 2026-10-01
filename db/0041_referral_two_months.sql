-- 2026-10-01 (owner): "make the reward 2 free months". A redeemed referral
-- now gives the inviter AND the new friend two months of Plus, not Plus
-- forever. Accounts that already hold a referral grant keep it (their rows
-- have current_period_end null and has_plus() already says yes).
--
-- Rules (built from the live definition, pg_get_functiondef 2026-10-01):
-- - paying (Stripe or Apple) or a permanent grant (comp, founding, the old
--   forever-referrals): nothing changes;
-- - otherwise: two months from now, or two more months on top of a
--   time-limited referral grant that is still running (an inviter who brings
--   several friends stacks them).
create or replace function public.grant_referral_plus(p_uid uuid)
 returns void
 language plpgsql
 security definer
 set search_path to 'public'
as $function$
declare
  r public.subscriptions%rowtype;
begin
  select * into r from public.subscriptions where user_id = p_uid;
  if r.user_id is not null and public.has_plus(p_uid)
     and (r.stripe_subscription_id is not null or r.provider = 'apple' or r.current_period_end is null) then
    return;                       -- paying, or Plus with no end date: leave it
  end if;
  insert into public.subscriptions (user_id, status, plan, current_period_end)
  values (p_uid, 'active', 'referral', now() + interval '2 months')
  on conflict (user_id) do update
     set status = 'active', plan = 'referral',
         current_period_end = greatest(coalesce(public.subscriptions.current_period_end, now()), now())
                              + interval '2 months'
   where public.subscriptions.stripe_subscription_id is null
     and coalesce(public.subscriptions.provider, '') <> 'apple';   -- never touch paid rows
end;
$function$;
revoke all on function public.grant_referral_plus(uuid) from public, anon, authenticated;
grant execute on function public.grant_referral_plus(uuid) to service_role;
