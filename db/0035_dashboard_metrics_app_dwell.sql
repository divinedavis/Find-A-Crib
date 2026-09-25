-- dashboard_metrics: measure time in the iPhone app apart from time on the
-- website (2026-09-24). Adds `dwell_app`; `dwell` is now web sessions only, and
-- no longer counts the app's '/app' launch row as a second hit next to its
-- app_open event (that made each bare launch a 2-hit 0s "engaged" session).
--
-- Edited from pg_get_functiondef of the live function; applied to production
-- 2026-09-24 through the Management API SQL endpoint. Grants are unchanged by
-- create or replace.
CREATE OR REPLACE FUNCTION public.dashboard_metrics(p_range text DEFAULT 'all'::text, p_ios_builds text[] DEFAULT NULL::text[])
 RETURNS jsonb
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
with
  bounds as (
    select case lower(coalesce(p_range, 'all'))
      when 'today' then ((now() at time zone 'America/New_York')::date)::timestamp
                          at time zone 'America/New_York'
      when 'month' then (date_trunc('month', now() at time zone 'America/New_York'))
                          at time zone 'America/New_York'
      when '3m'    then now() - interval '3 months'
      when '6m'    then now() - interval '6 months'
      else '-infinity'::timestamptz
    end as since
  ),
  -- owner's anonymous visitor ids, learned from either log table
  mine as (
    select visitor_id from public.visits
      where user_id = 'af2629f7-1121-4bee-8a2b-cede9318c864' and visitor_id is not null
    union
    select visitor_id from public.events
      where user_id = 'af2629f7-1121-4bee-8a2b-cede9318c864' and visitor_id is not null
  ),
  -- The iPhone app writes to events only, never to visits, so until
  -- 2026-09-21 app users were in no visitor, DAU/MAU, retention or activation
  -- figure — 104 of them in the previous 30 days. p_ios_builds is the list of
  -- builds that ever reached the App Store (api_server reads it from
  -- appstore.json). Anything else is a simulator, TestFlight or App Review:
  -- one UI-test run is a fresh visitor id launching the app 150 times, and
  -- twenty of those read as twenty users. Null = no filter.
  ios_ev as (
    select e.* from public.events e
    where e.props->>'platform' = 'ios'
      and (p_ios_builds is null or e.props->>'build' = any(p_ios_builds))
  ),
  -- Cleaned, UNRANGED. The fixed-window metrics (DAU/MAU, retention) read from
  -- these; the ranged views below are built on top.
  v_all as (
    select visitor_id, user_id, path, referrer, created_at from public.visits
    where user_id is distinct from 'af2629f7-1121-4bee-8a2b-cede9318c864'
      and visitor_id is not null
      and visitor_id not in (select visitor_id from mine)
      and not (coalesce(referrer,'') = '' and (
        path like '/building/%' or path like '/borough/%' or path like '/neighborhood/%'))
    union all
    -- One app launch stands in for one page load.
    select visitor_id, user_id, '/app' as path, 'ios-app' as referrer, created_at from ios_ev
    where event = 'app_open'
      and user_id is distinct from 'af2629f7-1121-4bee-8a2b-cede9318c864'
      and visitor_id is not null
      and visitor_id not in (select visitor_id from mine)
  ),
  ev_all as (
    select * from public.events
    where user_id is distinct from 'af2629f7-1121-4bee-8a2b-cede9318c864'
      and visitor_id is not null
      and visitor_id not in (select visitor_id from mine)
      and (props->>'platform' is distinct from 'ios'
           or p_ios_builds is null or props->>'build' = any(p_ios_builds))
  ),
  v  as (select v_all.*  from v_all,  bounds where v_all.created_at  >= bounds.since),
  ev as (select ev_all.* from ev_all, bounds where ev_all.created_at >= bounds.since),
  -- A RETURN IS A DIFFERENT DAY, not a second page load.
  --
  -- This counted anyone with more than one row in `visits` as returning, and a
  -- row is one page load: landing on the map and opening a single building page
  -- made someone a "returning visitor" forty seconds after they arrived. Across
  -- all 864 visitors that read 275 returning (32%) when only 81 (9%) had ever
  -- come back on another day — 194 of them never left at all. It also filled
  -- the channel donut with "internal / same-site", which is not a channel that
  -- brings anyone back, it is the site linking to itself mid-visit.
  --
  -- `days` is therefore the basis for every returning/one-time figure below.
  pv as (
    select visitor_id,
           count(*) as visits,
           count(distinct (created_at at time zone 'America/New_York')::date) as days,
           bool_or(user_id is not null) as signed_up
    from v group by visitor_id
  ),
  adv as (
    select distinct visitor_id from v
    where path ~* 'gclid|gad_source|gbraid' and visitor_id is not null
  ),
  fac_users as (
    select user_id from public.visits where user_id is not null
    union select user_id from public.events where user_id is not null
    union select user_id from public.saved_buildings
    union select user_id from public.subscriptions
    union select user_id from public.saved_searches
  ),
  -- The first hit of each day a visitor was here. That row carries the referrer
  -- that actually brought them back; every later hit that day carries wherever
  -- they happened to be on the site, which is why the donut used to be mostly
  -- "internal".
  day_first as (
    select distinct on (visitor_id, (created_at at time zone 'America/New_York')::date)
           visitor_id,
           (created_at at time zone 'America/New_York')::date as d,
           path, referrer, created_at
    from v
    order by visitor_id, (created_at at time zone 'America/New_York')::date, created_at
  ),
  ranked_days as (
    select *, row_number() over (partition by visitor_id order by d) as day_rn
    from day_first
  ),
  -- One row per RETURN: a day after the visitor's first day.
  returns as (select * from ranked_days where day_rn > 1),
  searchers as (select distinct visitor_id from ev where event = 'search'),
  viewers   as (select distinct visitor_id from ev where event = 'building_view'),
  today_new as (
    select distinct visitor_id from v_all t
    where (t.created_at at time zone 'America/New_York')::date
        = (now() at time zone 'America/New_York')::date
      and not exists (
        select 1 from v_all p where p.visitor_id = t.visitor_id
          and (p.created_at at time zone 'America/New_York')::date
            < (now() at time zone 'America/New_York')::date)
  ),
  openers_today as (
    select distinct visitor_id from ev_all
    where event = 'building_view'
      and (created_at at time zone 'America/New_York')::date
        = (now() at time zone 'America/New_York')::date
  ),
  days14 as (
    select (created_at at time zone 'America/New_York')::date as d,
           count(*) as views, count(distinct visitor_id) as visitors
    from v_all
    where (created_at at time zone 'America/New_York')::date
        >= (now() at time zone 'America/New_York')::date - 13
    group by 1
  ),

  -- ---- engagement: fixed windows, never re-scoped by the picker -----------
  active_days as (
    select distinct visitor_id, (created_at at time zone 'America/New_York')::date as d
    from v_all
  ),
  eng as (
    select
      (select count(distinct visitor_id) from active_days
         where d = (now() at time zone 'America/New_York')::date) as dau,
      (select count(distinct visitor_id) from active_days
         where d > (now() at time zone 'America/New_York')::date - 7)  as wau,
      (select count(distinct visitor_id) from active_days
         where d > (now() at time zone 'America/New_York')::date - 30) as mau,
      -- Yesterday, and the mean of the last seven FULL days: the stickiness
      -- ratio is built on these, not on a today that is still filling (at
      -- 07:40 it read 1.3%, by 10:00 the same day 4.4%).
      (select count(distinct visitor_id) from active_days
         where d = (now() at time zone 'America/New_York')::date - 1) as dau_yesterday,
      (select coalesce(round(avg(c), 1), 0) from (
         select d, count(distinct visitor_id) as c from active_days
          where d <  (now() at time zone 'America/New_York')::date
            and d >= (now() at time zone 'America/New_York')::date - 7
          group by d) x) as dau_7avg,
      -- The window before each window, for growth rates.
      (select count(distinct visitor_id) from active_days
         where d >  (now() at time zone 'America/New_York')::date - 14
           and d <= (now() at time zone 'America/New_York')::date - 7)  as wau_prev,
      (select count(distinct visitor_id) from active_days
         where d >  (now() at time zone 'America/New_York')::date - 60
           and d <= (now() at time zone 'America/New_York')::date - 30) as mau_prev
  ),

  -- ---- retention: of visitors first seen at least N days ago, how many came
  -- back at least N days after that first visit. Null when no cohort is old
  -- enough, rather than 0 — an empty cohort is "unknown", not "all churned".
  firsts as (
    select visitor_id, min(created_at) as first_at, max(created_at) as last_at
    from v_all group by visitor_id
  ),
  -- A SECOND, DIFFERENT MEASURE: did they come back AT ALL inside the window,
  -- as opposed to `retained` above, which asks whether they were still showing
  -- up ON OR AFTER day N. Day-30 retention and "returned within 30 days" are
  -- not the same question and do not have the same answer -- the first is a
  -- survival rate, the second is a return rate, and published return-rate
  -- benchmarks mean the second one.
  --
  -- Built on `active_days`, so a return is a DIFFERENT DAY, matching the rule
  -- the ranged `pv.days` figures already use. The cohort is restricted to
  -- visitors whose first day is at least N days old, so every member has had
  -- the full window to come back; without that the newest visitors would be
  -- counted as non-returners purely for being new, and the rate would read low
  -- by construction.
  day_ranked as (
    select visitor_id, d,
           row_number() over (partition by visitor_id order by d) as rn
    from active_days
  ),
  vfirst as (
    select f.visitor_id, f.d as first_d, s.d as second_d
    from      (select visitor_id, d from day_ranked where rn = 1) f
    left join (select visitor_id, d from day_ranked where rn = 2) s using (visitor_id)
  ),
  ret as (
    select
      n,
      (select count(*) from firsts where first_at <= now() - (n || ' days')::interval) as cohort,
      (select count(*) from firsts
         where first_at <= now() - (n || ' days')::interval
           and last_at >= first_at + (n || ' days')::interval) as retained,
      (select count(*) from vfirst
         where first_d <= (now() at time zone 'America/New_York')::date - n) as win_cohort,
      (select count(*) from vfirst
         where first_d <= (now() at time zone 'America/New_York')::date - n
           and second_d is not null
           and second_d <= first_d + n) as win_returned
    from (values (1),(7),(30),(60),(90)) as t(n)
  ),

  -- ---- savers who came back: the return rate that a listings portal
  -- actually optimises. Zillow's ~3.5 visits per user per month are driven by
  -- saved-search alerts, not by habit, so the question is not "does everyone
  -- come back" but "does someone who saved a building or a search come back".
  -- Cohort: accounts whose FIRST save is at least 30 days old, so each member
  -- has had the whole window. Return: an active day (a visit row carrying
  -- their user_id) later than the save day and within 30 days of it. Fixed
  -- window; the range picker does not apply. Null when the cohort is empty.
  saver_first as (
    select user_id, min((created_at at time zone 'America/New_York')::date) as first_save
    from (select user_id, created_at from public.saved_buildings
          union all
          select user_id, created_at from public.saved_searches) s
    where user_id is not null
      and user_id is distinct from 'af2629f7-1121-4bee-8a2b-cede9318c864'
    group by user_id
  ),
  user_days as (
    select distinct user_id, (created_at at time zone 'America/New_York')::date as d
    from (select user_id, created_at from v_all  where user_id is not null
          union all
          select user_id, created_at from ev_all where user_id is not null) x
  ),
  saver_ret as (
    select
      (select count(*) from saver_first
         where first_save <= (now() at time zone 'America/New_York')::date - 30) as cohort,
      (select count(*) from saver_first f
         where first_save <= (now() at time zone 'America/New_York')::date - 30
           and exists (select 1 from user_days u
                         where u.user_id = f.user_id
                           and u.d > f.first_save
                           and u.d <= f.first_save + 30)) as returned,
      (select count(*) from saver_first) as savers
  ),

  -- ---- time on site, ranged -----------------------------------------------
  -- There is no timing beacon, so a session is reconstructed: every visit and
  -- event for one visitor_id, split wherever the gap exceeds 30 minutes (the
  -- same rule GA uses). Duration is last-hit minus first-hit.
  --
  -- THAT DEFINITION HAS A FLOOR THAT CANNOT BE ENGINEERED AWAY: nothing is
  -- logged when a page closes, so the final page of every session contributes
  -- zero. A one-hit session therefore measures 0s no matter how long the
  -- person actually read, which is why the median is taken over sessions with
  -- 2+ hits and `single_hit_pct` is reported next to it rather than folded in.
  -- Including the zeros would drag the median to literally 0 and mean nothing.
  -- The real number is somewhat higher than what this reports; treat it as a
  -- floor. Only a client-side unload/heartbeat ping would fix it.
  --
  -- The iPhone app and the website are measured apart (2026-09-24): `app` tags
  -- every hit, sessions split on it, and the payload carries `dwell` (web) and
  -- `dwell_app`. The app's '/app' rows in v are skipped here — each is the same
  -- instant as its app_open event, and counting both made every bare launch a
  -- 2-hit "engaged" session of 0s. The app logs nothing on backgrounding, so
  -- its last screen is unmeasured exactly as a web page's is: also a floor.
  hits as (
    select visitor_id, created_at, false as app from v
     where referrer is distinct from 'ios-app'
    union all
    -- A session hit must be something the VISITOR did. tile_served fires when
    -- an advertiser tile is rendered and tile_impression when it scrolls into
    -- view; neither requires the person to do anything, and tile_served alone
    -- now fires ~1,500 times a day. Counting them turned bounces into "engaged
    -- sessions" of a couple of seconds each and cut the reported median time on
    -- site from 104s to 29s on 2026-08-28 — a number the card then judged
    -- "below average" against the industry benchmark. Passive telemetry is not
    -- engagement.
    select visitor_id, created_at, (props->>'platform' = 'ios') is true as app from ev
     where event not in ('tile_served', 'tile_impression')
  ),
  marked as (
    select visitor_id, app, created_at,
      case when lag(created_at) over w is null
             or created_at - lag(created_at) over w > interval '30 minutes'
           then 1 else 0 end as starts
    from hits
    window w as (partition by visitor_id, app order by created_at)
  ),
  sessed as (
    select visitor_id, app, created_at,
      sum(starts) over (partition by visitor_id, app order by created_at
                        rows unbounded preceding) as sid
    from marked
  ),
  sess as (
    select visitor_id, app, sid, count(*) as n,
           extract(epoch from (max(created_at) - min(created_at))) as secs
    from sessed group by 1, 2, 3
  ),
  sess_web as (select * from sess where not app),
  sess_app as (select * from sess where app),

  -- ---- feature adoption, ranged: of the visitors active in the window, what
  -- share reached each feature. Denominator is active visitors, not accounts —
  -- most people never sign up, and hiding them flatters every rate.
  feat as (
    select
      (select count(*) from pv) as active,
      (select count(distinct visitor_id) from ev where event = 'search') as searched,
      (select count(distinct visitor_id) from ev where event = 'building_view') as viewed,
      (select count(distinct visitor_id) from ev where event = 'save') as saved,
      (select count(distinct visitor_id) from ev
         where event = 'outbound' and props->>'kind' = 'phone_reveal') as phone,
      (select count(distinct visitor_id) from ev
         where event = 'outbound' and props->>'kind' = 'research') as research
  ),

  -- ---- activation: the ordered path a new account is supposed to walk.
  -- Keyed on user_id, so it measures accounts, not anonymous traffic.
  acct_all as (
    select au.id, au.created_at
    from auth.users au
    where au.id <> 'af2629f7-1121-4bee-8a2b-cede9318c864'
      and au.id in (select user_id from fac_users)
  ),
  acct as (select id from acct_all where created_at >= (select since from bounds)),

  -- ---- growth, fixed 30-day windows, for the investor card -----------------
  -- Where each visitor's FIRST hit came from. `first_hit` is one row per
  -- visitor across all time, so a new visitor is one whose first day is
  -- inside the window.
  first_hit as (
    select distinct on (visitor_id) visitor_id, path, referrer, created_at,
           (created_at at time zone 'America/New_York')::date as d
    from v_all order by visitor_id, created_at
  ),
  new30 as (
    select *, case
        when path ~* 'gclid|gad_source|gbraid' then 'paid'
        when referrer = 'ios-app' then 'app'
        when path ~* '[?&]src=' then 'tagged'
        when coalesce(referrer,'') ~* 'google|bing|ecosia|brave|duckduckgo|yahoo|search' then 'organic'
        when coalesce(referrer,'') ~* 'findacrib\.com|accounts\.google|checkout\.stripe' then 'direct'
        when coalesce(referrer,'') = '' then 'direct'
        else 'referral' end as ch
    from first_hit
    where d > (now() at time zone 'America/New_York')::date - 30
  ),
  growth as (
    select
      (select count(*) from acct_all where created_at >  now() - interval '30 days') as accounts_30,
      (select count(*) from acct_all where created_at >  now() - interval '60 days'
                                      and created_at <= now() - interval '30 days') as accounts_prev30,
      (select count(*) from new30) as new_30,
      (select count(*) from first_hit
         where d >  (now() at time zone 'America/New_York')::date - 60
           and d <= (now() at time zone 'America/New_York')::date - 30) as new_prev30,
      (select coalesce(jsonb_object_agg(ch, n), '{}'::jsonb) from
         (select ch, count(*) as n from new30 group by ch) c) as new_by_channel,
      (select count(*) from public.referrals
         where status = 'redeemed'
           and coalesce(redeemed_at, created_at) > now() - interval '30 days') as referrals_30,
      (select count(distinct visitor_id) from ios_ev
         where created_at > now() - interval '30 days'
           and visitor_id not in (select visitor_id from mine)) as app_actives_30,
      (select count(distinct visitor_id) from ios_ev
         where created_at >  now() - interval '60 days'
           and created_at <= now() - interval '30 days'
           and visitor_id not in (select visitor_id from mine)) as app_actives_prev30
  )
select jsonb_build_object(
  'generated_at', now(),
  -- What the numbers below are scoped to, so the UI never has to guess.
  'range', lower(coalesce(p_range, 'all')),
  'since', (select case when since = '-infinity'::timestamptz then null else since end
              from bounds),
  'totals', jsonb_build_object(
    'visitors',  (select count(*) from pv),
    'visits',    (select coalesce(sum(visits), 0) from pv),
    -- Returning = seen in the range AND seen on an earlier day, whether that
    -- earlier day is inside the range or before it. `days` alone only counts
    -- days inside the range, so on "Today" this read 0 for everyone, every
    -- day, and "This month" missed anyone whose earlier visit was last month
    -- (owner, 2026-09-20). On 'all' nothing is before the range, so it is
    -- still days > 1.
    'returning', (select count(*) from pv
                   where days > 1
                      or visitor_id in (
                        select visitor_id from public.visits, bounds
                         where visitor_id is not null
                           and created_at < bounds.since)),
    -- Accounts CREATED in the window, not every account that has ever existed.
    -- The all-time count against a ranged visitor count is not just mislabelled,
    -- it produces a nonsense derived stat: the dashboard divides this by unique
    -- visitors, so 26 lifetime accounts over 1 visitor today printed a sign-up
    -- conversion of 2600%. On 'all' the bound is -infinity, so this is still
    -- every account.
    'accounts',  (select count(*) from acct),
    -- Every account ever, for the goals that say "all time" and for the
    -- alert-list and free-to-paid comparisons, which are not ranged either.
    'accounts_all', (select count(*) from acct_all)
  ),
  'dwell', jsonb_build_object(
    'sessions',        (select count(*) from sess_web),
    'engaged',         (select count(*) from sess_web where n > 1),
    'single_hit_pct',  (select case when count(*) = 0 then null
                          else round(100.0 * count(*) filter (where n = 1) / count(*), 1) end
                          from sess_web),
    'median_secs',     (select round(percentile_cont(0.5) within group (order by secs))
                          from sess_web where n > 1),
    'p75_secs',        (select round(percentile_cont(0.75) within group (order by secs))
                          from sess_web where n > 1),
    'p90_secs',        (select round(percentile_cont(0.90) within group (order by secs))
                          from sess_web where n > 1),
    'median_hits',     (select percentile_cont(0.5) within group (order by n) from sess_web),
    -- The GA-comparable figure, and the ONLY one that may be held against a
    -- published "average session duration": mean over EVERY session with the
    -- single-hit ones counted as the zeros they measure. That is precisely how
    -- GA computes it. The tile's headline median excludes those zeros, so it
    -- reads lower and must never be compared to an industry average directly —
    -- doing so understates the site by about a minute.
    'mean_all_secs',   (select round(avg(secs)) from sess_web),
    -- The median excludes single-hit sessions; say so in the payload so a
    -- future reader of this JSON cannot mistake it for all sessions.
    'basis', 'sessions with 2+ hits; 30-minute gap; last page unmeasured'
  ),
  'dwell_app', jsonb_build_object(
    'sessions',        (select count(*) from sess_app),
    'engaged',         (select count(*) from sess_app where n > 1),
    'single_hit_pct',  (select case when count(*) = 0 then null
                          else round(100.0 * count(*) filter (where n = 1) / count(*), 1) end
                          from sess_app),
    'median_secs',     (select round(percentile_cont(0.5) within group (order by secs))
                          from sess_app where n > 1),
    'p75_secs',        (select round(percentile_cont(0.75) within group (order by secs))
                          from sess_app where n > 1),
    'p90_secs',        (select round(percentile_cont(0.90) within group (order by secs))
                          from sess_app where n > 1),
    'median_hits',     (select percentile_cont(0.5) within group (order by n) from sess_app),
    'mean_all_secs',   (select round(avg(secs)) from sess_app),
    'basis', 'iPhone app; sessions with 2+ events; 30-minute gap; last screen unmeasured'
  ),
  'conversion', jsonb_build_object(
    'one_time_visitors',  (select count(*) from pv where days = 1),
    'one_time_signups',   (select count(*) from pv where days = 1 and signed_up),
    'returning_visitors', (select count(*) from pv where days > 1),
    'returning_signups',  (select count(*) from pv where days > 1 and signed_up)
  ),
  'returns', jsonb_build_object(
    'total', (select count(*) from returns),
    'paid',  (select count(*) from returns where path ~* 'gclid|gad_source|gbraid'),
    'by_channel', coalesce((
      select jsonb_object_agg(ch, n) from (
        select case
          when path ~* 'gclid|gad_source|gbraid' then 'paid_google_ads'
          when coalesce(referrer,'') ~* 'findacrib\.com|accounts\.google|checkout\.stripe' then 'internal_direct'
          when coalesce(referrer,'') ~* 'google|bing|ecosia|brave|duckduckgo|yahoo|search' then 'organic_search'
          when coalesce(referrer,'') = '' then 'direct_or_bookmark'
          else 'referral_other'
        end as ch, count(*) as n
        from returns group by 1) c), '{}'::jsonb)
  ),
  'hook', jsonb_build_object(
    'viewed_visitors',  (select count(*) from pv where visitor_id in (select visitor_id from viewers)),
    'viewed_returned',  (select count(*) from pv where days > 1 and visitor_id in (select visitor_id from viewers)),
    'viewed_signups',   (select count(*) from pv where signed_up and visitor_id in (select visitor_id from viewers)),
    'noview_visitors',  (select count(*) from pv where visitor_id not in (select visitor_id from viewers)),
    'noview_returned',  (select count(*) from pv where days > 1 and visitor_id not in (select visitor_id from viewers)),
    'noview_signups',   (select count(*) from pv where signed_up and visitor_id not in (select visitor_id from viewers)),
    'searched_visitors',(select count(*) from pv where visitor_id in (select visitor_id from searchers)),
    'searched_returned',(select count(*) from pv where days > 1 and visitor_id in (select visitor_id from searchers)),
    'searched_signups', (select count(*) from pv where signed_up and visitor_id in (select visitor_id from searchers))
  ),
  'ads', jsonb_build_object(
    'click_visits',    (select count(*) from v where path ~* 'gclid|gad_source|gbraid'),
    'visitors',        (select count(*) from adv),
    'signups',         (select count(*) from pv where signed_up and visitor_id in (select visitor_id from adv)),
    'returned',        (select count(*) from pv where days > 1 and visitor_id in (select visitor_id from adv)),
    'opened_listing',  (select count(*) from pv where visitor_id in (select visitor_id from adv)
                          and visitor_id in (select visitor_id from viewers))
  ),
  'referrals', jsonb_build_object(
    'opened',      (select count(distinct user_id) from ev
                      where event = 'referral_open' and props->>'via' = 'button'
                        and user_id is not null),
    'shared',      (select count(distinct user_id) from ev
                      where event = 'referral_share' and user_id is not null),
    -- Bounded like the two counts above it. This read the whole table, so a
    -- card whose other two tiles went to zero on "Today" went on reporting
    -- every redemption there had ever been — two of them from July and
    -- August, sitting under a September window. redeemed_at is the date the
    -- friend actually signed up; created_at only says when the link was made,
    -- and rows redeemed before that column existed have none.
    'redemptions', (select count(*) from public.referrals, bounds
                      where status = 'redeemed'
                        and coalesce(redeemed_at, created_at) >= bounds.since)
  ),

  -- ---- NEW: engagement. Fixed windows — the range picker does not apply.
  'engagement', (
    select jsonb_build_object(
      'dau', dau, 'wau', wau, 'mau', mau,
      'dau_yesterday', dau_yesterday, 'dau_7avg', dau_7avg,
      'wau_prev', wau_prev, 'mau_prev', mau_prev,
      -- The industry ratio, on a full day (the 7-day mean), not on today so
      -- far. Null rather than a divide-by-zero on a dead day.
      'stickiness', case when mau > 0 then round(dau_7avg::numeric / mau, 3) end,
      'stickiness_today', case when mau > 0 then round(dau::numeric / mau, 3) end,
      'wau_mau',    case when mau > 0 then round(wau::numeric / mau, 3) end,
      'wau_growth', case when wau_prev > 0 then round(wau::numeric / wau_prev - 1, 3) end,
      'mau_growth', case when mau_prev > 0 then round(mau::numeric / mau_prev - 1, 3) end,
      'fixed_windows', true)
    from eng),

  'growth', (
    select jsonb_build_object(
      'accounts_30', accounts_30, 'accounts_prev30', accounts_prev30,
      'accounts_growth', case when accounts_prev30 > 0
                           then round(accounts_30::numeric / accounts_prev30 - 1, 3) end,
      'new_30', new_30, 'new_prev30', new_prev30,
      'new_growth', case when new_prev30 > 0 then round(new_30::numeric / new_prev30 - 1, 3) end,
      'new_by_channel', new_by_channel,
      'referrals_30', referrals_30,
      -- Viral coefficient: friends who signed up through a referral link, per
      -- new account. Above 1 the product grows on its own; consumer apps
      -- usually sit well under 0.5.
      'k_factor', case when accounts_30 > 0 then round(referrals_30::numeric / accounts_30, 3) end,
      'app_actives_30', app_actives_30, 'app_actives_prev30', app_actives_prev30,
      'fixed_windows', true)
    from growth),

  'retention', coalesce((
    select jsonb_object_agg('d' || n, jsonb_build_object(
      'cohort', cohort, 'retained', retained,
      -- Null, not zero, when nobody is old enough to have been retained yet.
      'rate', case when cohort > 0 then round(retained::numeric / cohort, 3) end,
      -- `within_rate` is the RETURN rate -- came back on any later day inside
      -- the N-day window -- and it is the only figure here that may be held
      -- against a published "x% of visitors return within 30 days" benchmark.
      -- `rate` above is a survival rate and will always read lower. The window
      -- is fixed: the range picker does not apply to either.
      'within_cohort',   win_cohort,
      'within_returned', win_returned,
      'within_rate', case when win_cohort > 0
                       then round(win_returned::numeric / win_cohort, 3) end))
    from ret), '{}'::jsonb),

  'saver_return', (
    select jsonb_build_object(
      'savers', savers, 'cohort', cohort, 'returned', returned,
      'rate', case when cohort > 0 then round(returned::numeric / cohort, 3) end,
      'fixed_windows', true)
    from saver_ret),

  'adoption', (
    select jsonb_build_object(
      'active', active,
      'searched', searched, 'viewed', viewed, 'saved', saved,
      'phone_reveal', phone, 'research', research,
      'searched_rate', case when active > 0 then round(searched::numeric / active, 3) end,
      'viewed_rate',   case when active > 0 then round(viewed::numeric   / active, 3) end,
      'saved_rate',    case when active > 0 then round(saved::numeric    / active, 3) end)
    from feat),

  'activation', jsonb_build_object(
    'accounts',  (select count(*) from acct),
    'searched',  (select count(distinct a.id) from acct a
                    where exists (select 1 from ev_all e
                                    where e.user_id = a.id and e.event = 'search')),
    'viewed',    (select count(distinct a.id) from acct a
                    where exists (select 1 from ev_all e
                                    where e.user_id = a.id and e.event = 'building_view')),
    'saved',     (select count(distinct a.id) from acct a
                    where exists (select 1 from public.saved_buildings s where s.user_id = a.id))
  ),

  'saves', jsonb_build_object(
    'buildings',      (select count(*) from public.saved_buildings),
    'savers',         (select count(distinct user_id) from public.saved_buildings),
    'saved_searches', (select count(*) from public.saved_searches),
    'searchers',      (select count(distinct user_id) from public.saved_searches),
    'folders',        (select count(*) from public.categories)
  ),

  -- Current state, not a period count: there is no created_at on subscriptions,
  -- so this cannot honestly be ranged. 'founding' is the free grant of
  -- 2026-08-09 and is kept out of MRR alongside 'comp'.
  'subscriptions', jsonb_build_object(
    'paying', (select count(*) from public.subscriptions
                 where status in ('active','trialing') and plan = 'plus'
                   -- Stripe on the web, Apple in the app: both are paying
                   -- (2026-09-20 — two App Store subscribers were invisible here).
                   and (stripe_subscription_id is not null or provider = 'apple')
                   and user_id <> 'af2629f7-1121-4bee-8a2b-cede9318c864'
                   and (current_period_end is null or current_period_end > now())),
    'comped', (select count(*) from public.subscriptions
                 where status in ('active','trialing') and plan in ('comp','founding','referral')),
    'founding', (select count(*) from public.subscriptions
                 where status in ('active','trialing') and plan = 'founding'),
    'mrr',    round((select count(*) from public.subscriptions
                 where status in ('active','trialing') and plan = 'plus'
                   -- Stripe on the web, Apple in the app: both are paying
                   -- (2026-09-20 — two App Store subscribers were invisible here).
                   and (stripe_subscription_id is not null or provider = 'apple')
                   and user_id <> 'af2629f7-1121-4bee-8a2b-cede9318c864'
                   and (current_period_end is null or current_period_end > now())) * 4.99, 2)
  ),
  'alerts', (
    with subs as (
      select s.*
        from public.lottery_alert_subs s
       where s.email not in (
         select lower(email) from auth.users
          where id = 'af2629f7-1121-4bee-8a2b-cede9318c864')
    )
    select jsonb_build_object(
      'active',       (select count(*) from subs where unsubscribed_at is null),
      'total',        (select count(*) from subs),
      'signups',      (select count(*) from subs, bounds where subs.created_at >= bounds.since),
      'unsubscribed', (select count(*) from subs where unsubscribed_at is not null),
      'with_filter',  (select count(*) from subs
                        where unsubscribed_at is null
                          and (max_rent is not null or income is not null)),
      'lottery_only', (select count(*) from subs
                        where unsubscribed_at is null and not ('rerental' = any(kinds))),
      'rerental_only',(select count(*) from subs
                        where unsubscribed_at is null and not ('lottery' = any(kinds))),
      'emails_sent',  (select coalesce(sum(sent_count), 0) from subs),
      -- Clicks through /api/alerts/go (db/0030). Scanner hits and HEADs are
      -- stored but never counted. `emailed` is the click-rate denominator:
      -- every subscriber who has had at least the welcome.
      'emailed',      (select count(*) from subs where welcomed_at is not null),
      'clickers',     (select count(distinct c.sub_id) from public.alert_clicks c
                         join subs on subs.id = c.sub_id, bounds
                        where not c.is_bot and c.clicked_at >= bounds.since),
      'clicks',       (select count(*) from public.alert_clicks c
                         join subs on subs.id = c.sub_id, bounds
                        where not c.is_bot and c.clicked_at >= bounds.since),
      'bot_clicks',   (select count(*) from public.alert_clicks c
                         join subs on subs.id = c.sub_id, bounds
                        where c.is_bot and c.clicked_at >= bounds.since),
      -- A tapped push notification is the same act as a clicked link in the
      -- email, so the dashboard's alert-click tile counts both (owner,
      -- 2026-09-20). Kept as separate keys so the split stays readable.
      -- Released builds only (ios_ev): 26 "people" tapped a notification in
      -- September, 16 of them simulators on TestFlight builds.
      'push_opens',   (select count(*) from ios_ev e, bounds
                        where e.event = 'push_open' and e.created_at >= bounds.since),
      'push_openers', (select count(distinct coalesce(e.user_id::text, e.visitor_id)) from ios_ev e, bounds
                        where e.event = 'push_open' and e.created_at >= bounds.since),
      -- The push side of the "people we could reach" denominator.
      'push_reach',   (select count(distinct user_id) from public.device_tokens),
      'clicks_by_kind', coalesce((
        select jsonb_object_agg(email_kind, n) from (
          select c.email_kind, count(*) as n
            from public.alert_clicks c join subs on subs.id = c.sub_id, bounds
           where not c.is_bot and c.clicked_at >= bounds.since
           group by c.email_kind) k), '{}'::jsonb),
      'clicks_since', (select min(clicked_at) from public.alert_clicks),
      'today',        (select count(*) from subs
                        where created_at >= ((now() at time zone 'America/New_York')::date)::timestamp
                                             at time zone 'America/New_York'),
      'by_borough',   coalesce((
        select jsonb_object_agg(b, n) from (
          select b, count(*) as n
            from subs, unnest(subs.boroughs) as b
           where subs.unsubscribed_at is null
           group by b) x), '{}'::jsonb))
  ),
  'today', jsonb_build_object(
    'visitors', (select count(distinct visitor_id) from v_all
                   where (created_at at time zone 'America/New_York')::date
                       = (now() at time zone 'America/New_York')::date),
    'visits',   (select count(*) from v_all
                   where (created_at at time zone 'America/New_York')::date
                       = (now() at time zone 'America/New_York')::date),
    'new_visitors',       (select count(*) from today_new),
    'new_opened_listing', (select count(*) from today_new t
                             where t.visitor_id in (select visitor_id from openers_today)),
    'signups', (select count(*) from auth.users au
                  where au.id <> 'af2629f7-1121-4bee-8a2b-cede9318c864'
                    and au.id in (select user_id from fac_users)
                    and (au.created_at at time zone 'America/New_York')::date
                      = (now() at time zone 'America/New_York')::date)
  ),
  'sparkline', coalesce((
    select jsonb_agg(jsonb_build_object('date', d, 'views', views, 'visitors', visitors) order by d)
    from days14), '[]'::jsonb),
  'events', coalesce((
    select jsonb_object_agg(event, n) from (select event, count(*) as n from ev group by 1) e),
    '{}'::jsonb)
)
$function$

;
