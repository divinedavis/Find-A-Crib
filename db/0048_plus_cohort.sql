-- Free-to-paid by the dashboard's range (owner, 2026-10-05: "this tile should
-- also update based on the time filter selected"). subscriptions has no start
-- date, so the range is a cohort: of the accounts CREATED in the range, how
-- many pay now. since = null is every account (the old all-time number).
-- Paying = status 'active' only: since 2026-10-04 Plus has a first-month
-- trial, and 'trialing' (Stripe, and Apple intro offers from the same day)
-- has not paid yet — counted separately.
create or replace function public.dashboard_plus_cohort(since timestamptz default null)
returns jsonb
language sql stable security definer
set search_path = public
as $$
  with acc as (
    select u.id from auth.users u
    where (since is null or u.created_at >= since)
      and u.id not in (select public.dashboard_excluded_ids())
  ), live as (
    select s.* from public.subscriptions s join acc on acc.id = s.user_id
    where s.plan = 'plus' and (s.current_period_end is null or s.current_period_end > now())
      and (s.stripe_subscription_id is not null or s.provider = 'apple')
  )
  select jsonb_build_object(
    'accounts', (select count(*) from acc),
    'paying', (select count(*) from live where status = 'active'),
    'trialing', (select count(*) from live where status = 'trialing'));
$$;
revoke all on function public.dashboard_plus_cohort(timestamptz) from public, anon, authenticated;
grant execute on function public.dashboard_plus_cohort(timestamptz) to service_role;
