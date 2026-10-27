-- Free to Plus over time, next to free-to-paid on the owner dashboard's
-- metrics chart (owner, 2026-10-26: "free to plus %", counting trials).
--
-- dashboard_conversion_trend() gains two fields per day:
--    plus     accounts in Plus by that day, counting the free first month:
--             plan plus, status active or trialing, unexpired, Stripe or
--             Apple (no comps, founding or referral), dated by started_at;
--    f2plus   plus over the accounts created by then.
-- Like f2p it reads who is in Plus NOW, so someone who left drops out of
-- the past too. Everything else is 0062 unchanged.

create or replace function public.dashboard_conversion_trend(p_ios_builds text[] default null, p_from date default '2026-08-01')
returns jsonb
language sql stable security definer
set search_path = public
as $$
with
  mine as (
    select visitor_id from public.visits
      where user_id in (select public.dashboard_excluded_ids()) and visitor_id is not null
    union
    select visitor_id from public.events
      where user_id in (select public.dashboard_excluded_ids()) and visitor_id is not null
  ),
  v_all as (
    select visitor_id, created_at from public.visits
    where (user_id is null or user_id not in (select public.dashboard_excluded_ids()))
      and visitor_id is not null
      and visitor_id not in (select visitor_id from mine)
      and not (coalesce(referrer,'') = '' and (
        path like '/building/%' or path like '/borough/%' or path like '/neighborhood/%'))
    union all
    select e.visitor_id, e.created_at from public.events e
    where e.event = 'app_open'
      and e.props->>'platform' = 'ios'
      and (p_ios_builds is null or e.props->>'build' = any(p_ios_builds))
      and (e.user_id is null or e.user_id not in (select public.dashboard_excluded_ids()))
      and e.visitor_id is not null
      and e.visitor_id not in (select visitor_id from mine)
  ),
  vd as (
    select distinct visitor_id, (created_at at time zone 'America/New_York')::date as d from v_all
  ),
  ranked as (select visitor_id, d, row_number() over (partition by visitor_id order by d) as rn from vd),
  vfirst as (
    select f.visitor_id, f.d as first_d, s.d as second_d
    from      (select visitor_id, d from ranked where rn = 1) f
    left join (select visitor_id, d from ranked where rn = 2) s using (visitor_id)
  ),
  -- Every account, as dashboard_plus_cohort counts them, so the line's last
  -- point is the free-to-paid tile's all-time number.
  acct as (
    select (au.created_at at time zone 'America/New_York')::date as d
    from auth.users au
    where au.id not in (select public.dashboard_excluded_ids())
  ),
  paying as (
    select (s.paid_since at time zone 'America/New_York')::date as d
    from public.subscriptions s
    where s.plan = 'plus' and s.status = 'active' and s.paid_since is not null
      and (s.current_period_end is null or s.current_period_end > now())
      and (s.stripe_subscription_id is not null or s.provider = 'apple')
      and s.user_id not in (select public.dashboard_excluded_ids())
  ),
  -- Free to Plus (owner, 2026-10-26): everyone who joined Plus, counting
  -- the free first month. Same real-subscriber rule as paying, plus
  -- 'trialing', dated by started_at (paid_since is only set once paying).
  plus as (
    select (s.started_at at time zone 'America/New_York')::date as d
    from public.subscriptions s
    where s.plan = 'plus' and s.status in ('active', 'trialing') and s.started_at is not null
      and (s.current_period_end is null or s.current_period_end > now())
      and (s.stripe_subscription_id is not null or s.provider = 'apple')
      and s.user_id not in (select public.dashboard_excluded_ids())
  ),
  days as (
    select generate_series(p_from, (now() at time zone 'America/New_York')::date, interval '1 day')::date as d
  )
select coalesce(jsonb_agg(jsonb_build_object(
  'date', to_char(x.d, 'YYYY-MM-DD'),
  'd30_cohort', x.cohort, 'd30_returned', x.returned,
  'd30', case when x.cohort > 0 then round(100.0 * x.returned / x.cohort, 2) end,
  'accounts', x.accounts, 'paying', x.paid,
  'f2p', case when x.accounts > 0 then round(100.0 * x.paid / x.accounts, 3) end,
  'plus', x.plus,
  'f2plus', case when x.accounts > 0 then round(100.0 * x.plus / x.accounts, 3) end) order by x.d), '[]'::jsonb)
from (
  select days.d,
    (select count(*) from vfirst where first_d between days.d - 59 and days.d - 30) as cohort,
    (select count(*) from vfirst where first_d between days.d - 59 and days.d - 30
       and second_d is not null and second_d <= first_d + 30) as returned,
    (select count(*) from acct where acct.d <= days.d) as accounts,
    (select count(*) from paying where paying.d <= days.d) as paid,
    (select count(*) from plus where plus.d <= days.d) as plus
  from days) x
$$;

revoke all on function public.dashboard_conversion_trend(text[], date) from public, anon, authenticated;
grant execute on function public.dashboard_conversion_trend(text[], date) to service_role;
