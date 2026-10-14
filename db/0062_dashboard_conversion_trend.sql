-- D30 return rate and free-to-paid conversion over time, for the owner
-- dashboard's metrics chart (owner, 2026-10-13: "can we track our d/30 over
-- time in our line graph as a filter selection? can we track free to paid
-- conversion over time on the line graph as a filter too?").
--
-- 1. subscriptions.paid_since: the first moment an account was paying. The
--    table had no start date (db/0048 says so), so free-to-paid could only
--    be a current number. A trigger stamps it the first time a row becomes
--    'active'; the backfill uses Apple's first production purchase
--    notification for App Store subscribers and the row's updated_at for
--    Stripe (rows that have never changed state since they started paying).
--
-- 2. dashboard_conversion_trend(): one row per New York day from p_from:
--    d30        of the visitors first seen 30-59 days before that day (so
--               every one has had the full 30 days), the share who came back
--               on a different day within 30 days of their first — the same
--               return-rate rule as the investor tile's within_rate (db/0046),
--               on a rolling 30-day cohort so the line reaches today;
--    f2p        paying accounts (as dashboard_plus_cohort counts them:
--               active, unexpired, Stripe or Apple — no comps, founding,
--               referral or trials) whose paid_since is on or before that
--               day, over the accounts created by then. It reads people who
--               pay NOW: someone who paid and cancelled drops out of the past
--               too, so the line can't overstate.

alter table public.subscriptions add column if not exists paid_since timestamptz;

create or replace function public.subscriptions_stamp_paid_since()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if new.status = 'active' and new.paid_since is null then
    new.paid_since := now();
  end if;
  return new;
end $$;

drop trigger if exists subscriptions_paid_since on public.subscriptions;
create trigger subscriptions_paid_since before insert or update on public.subscriptions
  for each row execute function public.subscriptions_stamp_paid_since();

-- Backfill (the trigger fires on this update too, but coalesce wins first).
update public.subscriptions s
set paid_since = coalesce(
  (select min(n.signed_at) from public.apple_notifications n
    where n.user_id = s.user_id and n.environment = 'Production'
      and n.notification_type in ('SUBSCRIBED', 'DID_RENEW', 'OFFER_REDEEMED')),
  s.updated_at)
where s.status = 'active' and s.paid_since is null;

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
  days as (
    select generate_series(p_from, (now() at time zone 'America/New_York')::date, interval '1 day')::date as d
  )
select coalesce(jsonb_agg(jsonb_build_object(
  'date', to_char(x.d, 'YYYY-MM-DD'),
  'd30_cohort', x.cohort, 'd30_returned', x.returned,
  'd30', case when x.cohort > 0 then round(100.0 * x.returned / x.cohort, 2) end,
  'accounts', x.accounts, 'paying', x.paid,
  'f2p', case when x.accounts > 0 then round(100.0 * x.paid / x.accounts, 3) end) order by x.d), '[]'::jsonb)
from (
  select days.d,
    (select count(*) from vfirst where first_d between days.d - 59 and days.d - 30) as cohort,
    (select count(*) from vfirst where first_d between days.d - 59 and days.d - 30
       and second_d is not null and second_d <= first_d + 30) as returned,
    (select count(*) from acct where acct.d <= days.d) as accounts,
    (select count(*) from paying where paying.d <= days.d) as paid
  from days) x
$$;

revoke all on function public.dashboard_conversion_trend(text[], date) from public, anon, authenticated;
grant execute on function public.dashboard_conversion_trend(text[], date) to service_role;
revoke all on function public.subscriptions_stamp_paid_since() from public, anon, authenticated;
