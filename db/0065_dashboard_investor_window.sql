-- The owner dashboard's investor card over a chosen window (owner,
-- 2026-10-19: "this widget should allow me to filter for 30, 60, 90, all
-- time"). dashboard_metrics() fixes that card to 30 days; this returns the
-- same keys for the last p_days New York days (null = all time), so the page
-- swaps them in when the card's own picker moves off 30.
--
-- Windowed: actives (engagement.mau), new accounts, new visitors by channel,
-- referrals per new account, iPhone app actives, and each against the window
-- before it (null on all time: there is no window before it). Retention is
-- the return rate of the visitors who ARRIVED over a p_days window that ended
-- n days ago, so every one of them has had the full n days to come back
-- (on all time: every visitor at least n days old, as dashboard_metrics
-- counts it). DAU/WAU and stickiness stay with dashboard_metrics: they are
-- fixed-length by definition.
--
-- The cleaning (mine, ios_ev, v_all, fac_users, acct_all, the channel rules)
-- is copied from dashboard_metrics as it stands live on 2026-10-19; change
-- both together. At p_days = 30 every count except retention equals that
-- function's (checked when this was applied).

create or replace function public.dashboard_investor(p_days int default 30,
                                                     p_ios_builds text[] default null)
returns jsonb language sql security definer set search_path = public as $$
with
  w as (
    select (now() at time zone 'America/New_York')::date as today,
           -- All time = a window wider than the data, with nothing before it.
           case when p_days is null then 36500
                else least(greatest(p_days, 1), 36500) end as n
  ),
  mine as (
    select visitor_id from public.visits
      where user_id in (select public.dashboard_excluded_ids()) and visitor_id is not null
    union
    select visitor_id from public.events
      where user_id in (select public.dashboard_excluded_ids()) and visitor_id is not null
  ),
  ios_ev as (
    select e.* from public.events e
    where e.props->>'platform' = 'ios'
      and (p_ios_builds is null or e.props->>'build' = any(p_ios_builds))
  ),
  v_all as (
    select visitor_id, user_id, path, referrer, created_at from public.visits
    where (user_id is null or user_id not in (select public.dashboard_excluded_ids()))
      and visitor_id is not null
      and visitor_id not in (select visitor_id from mine)
      and not (coalesce(referrer,'') = '' and (
        path like '/building/%' or path like '/borough/%' or path like '/neighborhood/%'))
    union all
    select visitor_id, user_id, '/app' as path, 'ios-app' as referrer, created_at from ios_ev
    where event = 'app_open'
      and (user_id is null or user_id not in (select public.dashboard_excluded_ids()))
      and visitor_id is not null
      and visitor_id not in (select visitor_id from mine)
  ),
  active_days as (
    select distinct visitor_id, (created_at at time zone 'America/New_York')::date as d
    from v_all
  ),
  day_ranked as (
    select visitor_id, d, row_number() over (partition by visitor_id order by d) as rn
    from active_days
  ),
  vfirst as (
    select f.visitor_id, f.d as first_d, s.d as second_d
    from      (select visitor_id, d from day_ranked where rn = 1) f
    left join (select visitor_id, d from day_ranked where rn = 2) s using (visitor_id)
  ),
  fac_users as (
    select user_id from public.visits where user_id is not null
    union select user_id from public.events where user_id is not null
    union select user_id from public.saved_buildings
    union select user_id from public.subscriptions
    union select user_id from public.saved_searches
  ),
  acct_all as (
    select (au.created_at at time zone 'America/New_York')::date as d
    from auth.users au
    where au.id not in (select public.dashboard_excluded_ids())
      and au.id in (select user_id from fac_users)
  ),
  first_hit as (
    select distinct on (visitor_id) visitor_id, path, referrer,
           (created_at at time zone 'America/New_York')::date as d
    from v_all order by visitor_id, created_at
  ),
  new_w as (
    select case
        when path ~* 'gclid|gad_source|gbraid' then 'paid'
        when referrer = 'ios-app' then 'app'
        when path ~* '[?&]src=' then 'tagged'
        when coalesce(referrer,'') ~* 'google|bing|ecosia|brave|duckduckgo|yahoo|search' then 'organic'
        when coalesce(referrer,'') ~* 'findacrib\.com|accounts\.google|checkout\.stripe' then 'direct'
        when coalesce(referrer,'') = '' then 'direct'
        else 'referral' end as ch
    from first_hit, w where d > w.today - w.n
  ),
  app_days as (
    select distinct visitor_id, (created_at at time zone 'America/New_York')::date as d
    from ios_ev
    where visitor_id is not null and visitor_id not in (select visitor_id from mine)
  ),
  c as (
    select
      (select count(distinct visitor_id) from active_days where d > w.today - w.n) as mau,
      (select count(distinct visitor_id) from active_days
         where d > w.today - 2 * w.n and d <= w.today - w.n) as mau_prev,
      (select count(*) from acct_all where d > w.today - w.n) as accounts,
      (select count(*) from acct_all where d > w.today - 2 * w.n and d <= w.today - w.n) as accounts_prev,
      (select count(*) from new_w) as new_n,
      (select count(*) from first_hit where d > w.today - 2 * w.n and d <= w.today - w.n) as new_prev,
      (select coalesce(jsonb_object_agg(ch, k), '{}'::jsonb) from
         (select ch, count(*) as k from new_w group by ch) x) as new_by_channel,
      (select count(*) from public.referrals
         where status = 'redeemed'
           and (coalesce(redeemed_at, created_at) at time zone 'America/New_York')::date > w.today - w.n) as referrals,
      (select count(distinct visitor_id) from app_days where d > w.today - w.n) as app_actives,
      (select count(distinct visitor_id) from app_days
         where d > w.today - 2 * w.n and d <= w.today - w.n) as app_actives_prev
    from w
  ),
  ret as (
    select r.k,
      (select count(*) from vfirst
         where first_d <= w.today - r.k and first_d > w.today - r.k - w.n) as cohort,
      (select count(*) from vfirst
         where first_d <= w.today - r.k and first_d > w.today - r.k - w.n
           and second_d is not null and second_d <= first_d + r.k) as returned
    from w, (values (1),(7),(30)) as r(k)
  )
select jsonb_build_object(
  'days', p_days,
  'engagement', (select jsonb_build_object(
      'mau', mau, 'mau_prev', case when p_days is null then null else mau_prev end,
      'mau_growth', case when p_days is not null and mau_prev > 0
                      then round(mau::numeric / mau_prev - 1, 3) end) from c),
  'growth', (select jsonb_build_object(
      'accounts_30', accounts,
      'accounts_prev30', case when p_days is null then null else accounts_prev end,
      'accounts_growth', case when p_days is not null and accounts_prev > 0
                           then round(accounts::numeric / accounts_prev - 1, 3) end,
      'new_30', new_n, 'new_prev30', case when p_days is null then null else new_prev end,
      'new_by_channel', new_by_channel,
      'referrals_30', referrals,
      'k_factor', case when accounts > 0 then round(referrals::numeric / accounts, 3) end,
      'app_actives_30', app_actives,
      'app_actives_prev30', case when p_days is null then null else app_actives_prev end) from c),
  'retention', (select jsonb_object_agg('d' || k, jsonb_build_object(
      'within_cohort', cohort, 'within_returned', returned,
      'within_rate', case when cohort > 0 then round(returned::numeric / cohort, 3) end)) from ret)
)
$$;

revoke all on function public.dashboard_investor(int, text[]) from public, anon, authenticated;
grant execute on function public.dashboard_investor(int, text[]) to service_role;
