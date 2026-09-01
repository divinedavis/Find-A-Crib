-- The referral card's "links used" tile ignored the range picker.
--
-- 'opened' and 'shared' are counted off `ev`, which is bounded by the range;
-- 'redemptions' counted straight from public.referrals with no bound at all.
-- On 1 September 2026 the card read "0 clicked share · 0 shared a link · 2
-- links used" — the 2 were redeemed on 29 July and 8 August. Three tiles, two
-- windows, no label saying so.
--
-- Whole function replaced because it is a LANGUAGE sql function: there is no
-- way to patch one line of the body. Verified byte-identical to
-- 20260828200000 before this edit (pg_get_functiondef against the live
-- database), so this is that definition plus the bound.

CREATE OR REPLACE FUNCTION public.dashboard_metrics(p_range text DEFAULT 'all'::text)
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
  -- Cleaned, UNRANGED. The fixed-window metrics (DAU/MAU, retention) read from
  -- these; the ranged views below are built on top.
  v_all as (
    select * from public.visits
    where user_id is distinct from 'af2629f7-1121-4bee-8a2b-cede9318c864'
      and visitor_id is not null
      and visitor_id not in (select visitor_id from mine)
      and not (coalesce(referrer,'') = '' and (
        path like '/building/%' or path like '/borough/%' or path like '/neighborhood/%'))
  ),
  ev_all as (
    select * from public.events
    where user_id is distinct from 'af2629f7-1121-4bee-8a2b-cede9318c864'
      and visitor_id is not null
      and visitor_id not in (select visitor_id from mine)
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
         where d > (now() at time zone 'America/New_York')::date - 30) as mau
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
  hits as (
    select visitor_id, created_at from v
    union all
    -- A session hit must be something the VISITOR did. tile_served fires when
    -- an advertiser tile is rendered and tile_impression when it scrolls into
    -- view; neither requires the person to do anything, and tile_served alone
    -- now fires ~1,500 times a day. Counting them turned bounces into "engaged
    -- sessions" of a couple of seconds each and cut the reported median time on
    -- site from 104s to 29s on 2026-08-28 — a number the card then judged
    -- "below average" against the industry benchmark. Passive telemetry is not
    -- engagement.
    select visitor_id, created_at from ev
     where event not in ('tile_served', 'tile_impression')
  ),
  marked as (
    select visitor_id, created_at,
      case when lag(created_at) over w is null
             or created_at - lag(created_at) over w > interval '30 minutes'
           then 1 else 0 end as starts
    from hits
    window w as (partition by visitor_id order by created_at)
  ),
  sessed as (
    select visitor_id, created_at,
      sum(starts) over (partition by visitor_id order by created_at
                        rows unbounded preceding) as sid
    from marked
  ),
  sess as (
    select visitor_id, sid, count(*) as n,
           extract(epoch from (max(created_at) - min(created_at))) as secs
    from sessed group by 1, 2
  ),

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
  acct as (
    select au.id
    from auth.users au
    where au.id <> 'af2629f7-1121-4bee-8a2b-cede9318c864'
      and au.id in (select user_id from fac_users)
      and au.created_at >= (select since from bounds)
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
    'returning', (select count(*) from pv where days > 1),
    -- Accounts CREATED in the window, not every account that has ever existed.
    -- The all-time count against a ranged visitor count is not just mislabelled,
    -- it produces a nonsense derived stat: the dashboard divides this by unique
    -- visitors, so 26 lifetime accounts over 1 visitor today printed a sign-up
    -- conversion of 2600%. On 'all' the bound is -infinity, so this is still
    -- every account.
    'accounts',  (select count(*) from acct)
  ),
  'dwell', jsonb_build_object(
    'sessions',        (select count(*) from sess),
    'engaged',         (select count(*) from sess where n > 1),
    'single_hit_pct',  (select case when count(*) = 0 then null
                          else round(100.0 * count(*) filter (where n = 1) / count(*), 1) end
                          from sess),
    'median_secs',     (select round(percentile_cont(0.5) within group (order by secs))
                          from sess where n > 1),
    'p75_secs',        (select round(percentile_cont(0.75) within group (order by secs))
                          from sess where n > 1),
    'p90_secs',        (select round(percentile_cont(0.90) within group (order by secs))
                          from sess where n > 1),
    'median_hits',     (select percentile_cont(0.5) within group (order by n) from sess),
    -- The GA-comparable figure, and the ONLY one that may be held against a
    -- published "average session duration": mean over EVERY session with the
    -- single-hit ones counted as the zeros they measure. That is precisely how
    -- GA computes it. The tile's headline median excludes those zeros, so it
    -- reads lower and must never be compared to an industry average directly —
    -- doing so understates the site by about a minute.
    'mean_all_secs',   (select round(avg(secs)) from sess),
    -- The median excludes single-hit sessions; say so in the payload so a
    -- future reader of this JSON cannot mistake it for all sessions.
    'basis', 'sessions with 2+ hits; 30-minute gap; last page unmeasured'
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
      -- The industry ratio. Null rather than a divide-by-zero on a dead day.
      'stickiness', case when mau > 0 then round(dau::numeric / mau, 3) end,
      'wau_mau',    case when mau > 0 then round(wau::numeric / mau, 3) end,
      'fixed_windows', true)
    from eng),

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
                   and stripe_subscription_id is not null
                   and user_id <> 'af2629f7-1121-4bee-8a2b-cede9318c864'
                   and (current_period_end is null or current_period_end > now())),
    'comped', (select count(*) from public.subscriptions
                 where status in ('active','trialing') and plan in ('comp','founding','referral')),
    'founding', (select count(*) from public.subscriptions
                 where status in ('active','trialing') and plan = 'founding'),
    'mrr',    round((select count(*) from public.subscriptions
                 where status in ('active','trialing') and plan = 'plus'
                   and stripe_subscription_id is not null
                   and user_id <> 'af2629f7-1121-4bee-8a2b-cede9318c864'
                   and (current_period_end is null or current_period_end > now())) * 4.99, 2)
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

