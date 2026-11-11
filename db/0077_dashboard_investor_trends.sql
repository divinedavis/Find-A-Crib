-- Day-by-day lines for the owner dashboard's investor card (owner,
-- 2026-11-11: "i want to see the trend based on the filter i selected for
-- this widget for all tiles", design D: this period solid, the period before
-- it dashed).
--
-- Every line ENDS AT ITS TILE'S HEADLINE, so the tile and its chart can
-- never disagree:
--   * window counts (actives, new accounts, iPhone app actives) run as a
--     running total from the window's first day, so the solid line ends at
--     the headline and the dashed one at the "was" number;
--   * window ratios (organic share of new visitors, referrals per new
--     account, return rates) run as the ratio of those running totals;
--   * fixed-length figures (weekly actives, daily ÷ monthly actives, paying
--     share) are their usual definition evaluated on each day.
-- Index i of 'cur' is day (today - n + 1 + i); index i of 'prev' is n days
-- earlier. Return rates are keyed by ARRIVAL day instead: the window that
-- ended k days ago, as dashboard_investor counts them (start_d1/7/30 say
-- where each starts). All time has no window before it, so 'prev' is null.
--
-- The cleaning (mine, ios_ev, v_all, acct_all, the channel rules) is copied
-- from dashboard_investor (db/0065), which copies dashboard_metrics; change
-- all three together. Paying share: see subs below.

create or replace function public.dashboard_investor_trends(p_days int default 30,
                                                            p_ios_builds text[] default null)
returns jsonb language sql stable security definer set search_path = public as $$
with
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
  active_days as materialized (
    select distinct visitor_id, (created_at at time zone 'America/New_York')::date as d
    from v_all
  ),
  w as (
    select t.today,
           -- All time = from the first tracked day; capped so a bad
           -- argument can't ask for a million points.
           case when p_days is null then least(t.today - coalesce(t.first_d, t.today) + 1, 3660)
                else least(greatest(p_days, 1), 366) end as n,
           p_days is null as all_time
    from (select (now() at time zone 'America/New_York')::date as today,
                 (select min(d) from active_days) as first_d) t
  ),
  ix as (
    select i, w.today - w.n + 1 + i as dc, w.today - 2 * w.n + 1 + i as dp
    from w, generate_series(0, w.n - 1) as i
  ),
  -- ---- running totals over the window -------------------------------------
  firstin as (
    select visitor_id,
           min(d) filter (where d > w.today - w.n) as f_cur,
           min(d) filter (where d <= w.today - w.n) as f_prev
    from active_days, w where d > w.today - 2 * w.n group by visitor_id
  ),
  app_days as (
    select distinct visitor_id, (created_at at time zone 'America/New_York')::date as d
    from ios_ev
    where visitor_id is not null and visitor_id not in (select visitor_id from mine)
  ),
  app_firstin as (
    select visitor_id,
           min(d) filter (where d > w.today - w.n) as f_cur,
           min(d) filter (where d <= w.today - w.n) as f_prev
    from app_days, w where d > w.today - 2 * w.n group by visitor_id
  ),
  fac_users as (
    select user_id from public.visits where user_id is not null
    union select user_id from public.events where user_id is not null
    union select user_id from public.saved_buildings
    union select user_id from public.subscriptions
    union select user_id from public.saved_searches
  ),
  acct_all as materialized (
    select (au.created_at at time zone 'America/New_York')::date as d
    from auth.users au
    where au.id not in (select public.dashboard_excluded_ids())
      and au.id in (select user_id from fac_users)
  ),
  refs as (
    select (coalesce(redeemed_at, created_at) at time zone 'America/New_York')::date as d
    from public.referrals where status = 'redeemed'
  ),
  first_hit as (
    select distinct on (visitor_id) visitor_id, path, referrer,
           (created_at at time zone 'America/New_York')::date as d
    from v_all order by visitor_id, created_at
  ),
  new_ch as (
    select d, case
        when path ~* 'gclid|gad_source|gbraid' then 'paid'
        when referrer = 'ios-app' then 'app'
        when path ~* '[?&]src=' then 'tagged'
        when coalesce(referrer,'') ~* 'google|bing|ecosia|brave|duckduckgo|yahoo|search' then 'organic'
        when coalesce(referrer,'') ~* 'findacrib\.com|accounts\.google|checkout\.stripe' then 'direct'
        when coalesce(referrer,'') = '' then 'direct'
        else 'referral' end as ch
    from first_hit, w where d > w.today - 2 * w.n
  ),
  -- Per-day tallies, then running sums: one pass each instead of a scan per point.
  daily as (
    select ix.i,
      (select count(*) from firstin where f_cur = ix.dc) as act_c,
      (select count(*) from firstin where f_prev = ix.dp) as act_p,
      (select count(*) from app_firstin where f_cur = ix.dc) as app_c,
      (select count(*) from app_firstin where f_prev = ix.dp) as app_p,
      (select count(*) from acct_all where d = ix.dc) as acc_c,
      (select count(*) from acct_all where d = ix.dp) as acc_p,
      (select count(*) from refs where d = ix.dc) as ref_c,
      (select count(*) from refs where d = ix.dp) as ref_p,
      (select count(*) from new_ch where d = ix.dc) as new_c,
      (select count(*) from new_ch where d = ix.dp) as new_p,
      (select count(*) from new_ch where d = ix.dc and ch in ('organic', 'referral')) as org_c,
      (select count(*) from new_ch where d = ix.dp and ch in ('organic', 'referral')) as org_p
    from ix
  ),
  run as (
    select i,
      sum(act_c) over o as act_c, sum(act_p) over o as act_p,
      sum(app_c) over o as app_c, sum(app_p) over o as app_p,
      sum(acc_c) over o as acc_c, sum(acc_p) over o as acc_p,
      sum(ref_c) over o as ref_c, sum(ref_p) over o as ref_p,
      sum(new_c) over o as new_c, sum(new_p) over o as new_p,
      sum(org_c) over o as org_c, sum(org_p) over o as org_p
    from daily window o as (order by i)
  ),
  -- ---- fixed-length figures on each day -----------------------------------
  span as (
    select ix.i, x.d, x.cur from ix, lateral (values (ix.dc, true), (ix.dp, false)) as x(d, cur)
  ),
  dau as (
    select d, count(*) as c from active_days, w where d > w.today - 2 * w.n - 8 group by d
  ),
  -- Rolling 7- and 30-day distinct actives in one pass instead of a
  -- count(distinct) per day: each active day covers [d, d + L), minus what
  -- the visitor's previous active day already covered, so the pieces never
  -- overlap and a running sum of +1/-1 counts each visitor once. Days before
  -- the earliest point's lookback can't reach it and are skipped.
  ad as (
    select visitor_id, d, lag(d) over (partition by visitor_id order by d) as pd
    from active_days, w where d > w.today - 2 * w.n - 30
  ),
  cover as (
    select l.len, greatest(ad.d, coalesce(ad.pd + l.len, ad.d)) as s, ad.d + l.len as e
    from ad, (values (7), (30)) as l(len)
  ),
  cover_run as (
    select len, d, sum(sum(c)) over (partition by len order by d) as v
    from (select len, s as d, 1 as c from cover union all select len, e, -1 from cover) x
    group by len, d
  ),
  roll as (
    select s.i, s.cur,
      coalesce((select v from cover_run r where r.len = 7 and r.d <= s.d order by r.d desc limit 1), 0) as wau,
      coalesce((select v from cover_run r where r.len = 30 and r.d <= s.d order by r.d desc limit 1), 0) as mau,
      -- The mean of the seven full days before, as the stickiness tile has it.
      (select coalesce(avg(c), 0) from dau where dau.d < s.d and dau.d >= s.d - 7) as dau_7avg
    from span s where s.cur or not (select all_time from w)
  ),
  -- The tile's count is dashboard_plus_cohort(null).paying (api_server puts
  -- it there): live, non-trial subscriptions right now. Whether an ended or
  -- converted subscription was a trial on a past day isn't stored, so the
  -- line is today's paying customers by the day they started - it ends at
  -- the tile and never invents a past.
  subs as (
    select (x.started_at at time zone 'America/New_York')::date as s
    from public.subscriptions x
    where x.plan = 'plus' and x.status = 'active'
      and (x.stripe_subscription_id is not null or x.provider = 'apple')
      and (x.current_period_end is null or x.current_period_end > now())
      and x.user_id not in (select public.dashboard_excluded_ids())
      and x.started_at is not null
  ),
  pay as (
    select s.i, s.cur,
      (select count(*) from subs where subs.s <= s.d) as paying,
      (select count(*) from acct_all where acct_all.d <= s.d) as accounts
    from span s where s.cur or not (select all_time from w)
  ),
  -- ---- return rates by arrival day ----------------------------------------
  day_ranked as (
    select visitor_id, d, row_number() over (partition by visitor_id order by d) as rn
    from active_days
  ),
  vfirst as (
    select f.visitor_id, f.d as first_d, s.d as second_d
    from      (select visitor_id, d from day_ranked where rn = 1) f
    left join (select visitor_id, d from day_ranked where rn = 2) s using (visitor_id)
  ),
  ret_day as (
    select r.k, ix.i, wk.cur,
      (select count(*) from vfirst where first_d = wk.a) as cohort,
      (select count(*) from vfirst where first_d = wk.a
          and second_d is not null and second_d <= first_d + r.k) as returned
    from w, ix, (values (1), (7), (30)) as r(k),
         lateral (values (ix.dc - r.k, true), (ix.dp - r.k, false)) as wk(a, cur)
    where wk.cur or not w.all_time
  ),
  ret_run as (
    select k, i, cur,
      sum(cohort) over o as cohort, sum(returned) over o as returned
    from ret_day window o as (partition by k, cur order by i)
  ),
  ret_json as (
    select k,
      jsonb_agg(case when cohort > 0 then round(returned::numeric / cohort, 3) end order by i)
        filter (where cur) as c,
      jsonb_agg(case when cohort > 0 then round(returned::numeric / cohort, 3) end order by i)
        filter (where not cur) as p
    from ret_run group by k
  )
select jsonb_build_object(
  'days', p_days,
  'n', w.n,
  'start', w.today - w.n + 1,
  'start_d1', w.today - w.n + 1 - 1,
  'start_d7', w.today - w.n + 1 - 7,
  'start_d30', w.today - w.n + 1 - 30,
  'series', jsonb_build_object(
    'actives', (select jsonb_build_object('cur', jsonb_agg(act_c order by i),
        'prev', case when not w.all_time then jsonb_agg(act_p order by i) end) from run),
    'app_actives', (select jsonb_build_object('cur', jsonb_agg(app_c order by i),
        'prev', case when not w.all_time then jsonb_agg(app_p order by i) end) from run),
    'accounts', (select jsonb_build_object('cur', jsonb_agg(acc_c order by i),
        'prev', case when not w.all_time then jsonb_agg(acc_p order by i) end) from run),
    'organic', (select jsonb_build_object(
        'cur', jsonb_agg(case when new_c > 0 then round(org_c::numeric / new_c, 3) end order by i),
        'prev', case when not w.all_time then
          jsonb_agg(case when new_p > 0 then round(org_p::numeric / new_p, 3) end order by i) end) from run),
    'k_factor', (select jsonb_build_object(
        'cur', jsonb_agg(case when acc_c > 0 then round(ref_c::numeric / acc_c, 3) end order by i),
        'prev', case when not w.all_time then
          jsonb_agg(case when acc_p > 0 then round(ref_p::numeric / acc_p, 3) end order by i) end) from run),
    'wau', (select jsonb_build_object(
        'cur', jsonb_agg(wau order by i) filter (where cur),
        'prev', jsonb_agg(wau order by i) filter (where not cur)) from roll),
    'stickiness', (select jsonb_build_object(
        'cur', jsonb_agg(case when mau > 0 then round(dau_7avg / mau, 3) end order by i) filter (where cur),
        'prev', jsonb_agg(case when mau > 0 then round(dau_7avg / mau, 3) end order by i) filter (where not cur)) from roll),
    'paying', (select jsonb_build_object(
        'cur', jsonb_agg(case when accounts > 0 then round(paying::numeric / accounts, 4) end order by i) filter (where cur),
        'prev', jsonb_agg(case when accounts > 0 then round(paying::numeric / accounts, 4) end order by i) filter (where not cur)) from pay),
    'd1',  (select jsonb_build_object('cur', c, 'prev', p) from ret_json where k = 1),
    'd7',  (select jsonb_build_object('cur', c, 'prev', p) from ret_json where k = 7),
    'd30', (select jsonb_build_object('cur', c, 'prev', p) from ret_json where k = 30)
  ))
from w
$$;

revoke all on function public.dashboard_investor_trends(int, text[]) from public, anon, authenticated;
grant execute on function public.dashboard_investor_trends(int, text[]) to service_role;
