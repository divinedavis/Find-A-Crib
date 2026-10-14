-- Plus customers by the dashboard's range (owner, 2026-10-13: "instead of
-- showing paying customers tile, show plus customers and make sure the filter
-- impacts this tile"). Adds plus / plus_new / plus_web / plus_app to
-- dashboard_paying: everyone who had Plus at any point in [since, now] —
-- paying, in their free first month, or ended inside the range. The paying
-- keys stay for the free-to-paid tile. Same exclusions as before (owner,
-- comped/founding/referral). since = null is all time.
create or replace function public.dashboard_paying(since timestamptz default null)
returns jsonb
language sql stable security definer
set search_path = public
as $$
  with s as (
    select x.*, coalesce(x.current_period_end, case when x.status not in ('active', 'trialing') then x.updated_at end) as ends
      from public.subscriptions x
     where x.plan = 'plus'
       and (x.stripe_subscription_id is not null or x.provider = 'apple')
       and x.user_id not in (select public.dashboard_excluded_ids())
       and x.started_at is not null
  ), live as (
    select * from s where status in ('active', 'trialing') and (ends is null or ends > now())
  ), ended as (
    select * from s where status not in ('active', 'trialing') and (since is null or ends >= since)
  ), paid as (
    select * from live where status = 'active'
    union all
    select * from ended
  ), plus as (
    select * from live
    union all
    select * from ended
  )
  select jsonb_build_object(
    'plus', (select count(*) from plus),
    'plus_new', (select count(*) from plus where since is null or started_at >= since),
    'plus_web', (select count(*) from plus where provider = 'stripe'),
    'plus_app', (select count(*) from plus where provider = 'apple'),
    'paying', (select count(*) from paid),
    'new', (select count(*) from paid where since is null or started_at >= since),
    'ended', (select count(*) from ended),
    'trialing', (select count(*) from live where status = 'trialing'),
    'web', (select count(*) from paid where provider = 'stripe'),
    'app', (select count(*) from paid where provider = 'apple'),
    'paying_now', (select count(*) from live where status = 'active'));
$$;
revoke all on function public.dashboard_paying(timestamptz) from public, anon, authenticated;
grant execute on function public.dashboard_paying(timestamptz) to service_role;
