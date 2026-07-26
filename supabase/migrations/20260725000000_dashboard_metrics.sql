-- Owner-only analytics for the findacrib.com/dashboard page.
--
-- One SECURITY DEFINER function returns the whole dashboard as a single jsonb
-- blob so the Flask backend (findacrib-api) can fetch it in one PostgREST RPC
-- call with the service-role key. EXECUTE is granted to service_role only, so
-- the aggregate data is never reachable with the public anon/authenticated key;
-- the owner-email gate is enforced in the Flask layer on top of that.
--
-- Owner (divinejdavis@gmail.com) and search-engine crawlers are excluded with
-- the same rules as findacrib-report/traffic_report.py (CLEAN / BOT_FILTER),
-- so these numbers match the daily traffic email.

create or replace function public.dashboard_metrics()
returns jsonb
language sql
security definer
set search_path = public
as $$
with
  -- owner's anonymous visitor ids, learned from either log table
  mine as (
    select visitor_id from public.visits
      where user_id = 'af2629f7-1121-4bee-8a2b-cede9318c864' and visitor_id is not null
    union
    select visitor_id from public.events
      where user_id = 'af2629f7-1121-4bee-8a2b-cede9318c864' and visitor_id is not null
  ),
  -- cleaned visits: minus owner, minus null ids, minus referrer-less crawler
  -- hits on the SEO pages
  v as (
    select * from public.visits
    where user_id is distinct from 'af2629f7-1121-4bee-8a2b-cede9318c864'
      and visitor_id is not null
      and visitor_id not in (select visitor_id from mine)
      and not (coalesce(referrer,'') = '' and (
        path like '/building/%' or path like '/borough/%' or path like '/neighborhood/%'))
  ),
  ev as (
    select * from public.events
    where user_id is distinct from 'af2629f7-1121-4bee-8a2b-cede9318c864'
      and visitor_id is not null
      and visitor_id not in (select visitor_id from mine)
  ),
  pv as (
    select visitor_id, count(*) as visits, bool_or(user_id is not null) as signed_up
    from v group by visitor_id
  ),
  -- visitors who clicked a paid Google Ad at least once (gclid/gad_source/gbraid
  -- lands in the path); lets us ask whether ad traffic converts
  adv as (
    select distinct visitor_id from v
    where path ~* 'gclid|gad_source|gbraid' and visitor_id is not null
  ),
  -- real Find A Crib account holders: this auth is shared with Kinnkolk/JHF, so
  -- a "sign-up" only counts if the user left product activity here
  fac_users as (
    select user_id from public.visits where user_id is not null
    union select user_id from public.events where user_id is not null
    union select user_id from public.saved_buildings
    union select user_id from public.subscriptions
    union select user_id from public.saved_searches
  ),
  ordered as (
    select visitor_id, path, referrer,
           row_number() over (partition by visitor_id order by created_at) as rn
    from v
  ),
  returns as (select * from ordered where rn > 1),
  searchers as (select distinct visitor_id from ev where event = 'search'),
  viewers   as (select distinct visitor_id from ev where event = 'building_view'),
  today_new as (
    select distinct visitor_id from v t
    where (t.created_at at time zone 'America/New_York')::date
        = (now() at time zone 'America/New_York')::date
      and not exists (
        select 1 from v p where p.visitor_id = t.visitor_id
          and (p.created_at at time zone 'America/New_York')::date
            < (now() at time zone 'America/New_York')::date)
  ),
  openers_today as (
    select distinct visitor_id from ev
    where event = 'building_view'
      and (created_at at time zone 'America/New_York')::date
        = (now() at time zone 'America/New_York')::date
  ),
  days14 as (
    select (created_at at time zone 'America/New_York')::date as d,
           count(*) as views, count(distinct visitor_id) as visitors
    from v
    where (created_at at time zone 'America/New_York')::date
        >= (now() at time zone 'America/New_York')::date - 13
    group by 1
  )
select jsonb_build_object(
  'generated_at', now(),
  'totals', jsonb_build_object(
    'visitors',  (select count(*) from pv),
    'visits',    (select coalesce(sum(visits), 0) from pv),
    'returning', (select count(*) from pv where visits > 1),
    'accounts',  (select count(*) from fac_users
                    where user_id <> 'af2629f7-1121-4bee-8a2b-cede9318c864')
  ),
  'conversion', jsonb_build_object(
    'one_time_visitors',  (select count(*) from pv where visits = 1),
    'one_time_signups',   (select count(*) from pv where visits = 1 and signed_up),
    'returning_visitors', (select count(*) from pv where visits > 1),
    'returning_signups',  (select count(*) from pv where visits > 1 and signed_up)
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
    'viewed_returned',  (select count(*) from pv where visits > 1 and visitor_id in (select visitor_id from viewers)),
    'viewed_signups',   (select count(*) from pv where signed_up and visitor_id in (select visitor_id from viewers)),
    'noview_visitors',  (select count(*) from pv where visitor_id not in (select visitor_id from viewers)),
    'noview_returned',  (select count(*) from pv where visits > 1 and visitor_id not in (select visitor_id from viewers)),
    'noview_signups',   (select count(*) from pv where signed_up and visitor_id not in (select visitor_id from viewers)),
    'searched_visitors',(select count(*) from pv where visitor_id in (select visitor_id from searchers)),
    'searched_returned',(select count(*) from pv where visits > 1 and visitor_id in (select visitor_id from searchers)),
    'searched_signups', (select count(*) from pv where signed_up and visitor_id in (select visitor_id from searchers))
  ),
  'ads', jsonb_build_object(
    'click_visits',    (select count(*) from v where path ~* 'gclid|gad_source|gbraid'),
    'visitors',        (select count(*) from adv),
    'signups',         (select count(*) from pv where signed_up and visitor_id in (select visitor_id from adv)),
    'returned',        (select count(*) from pv where visits > 1 and visitor_id in (select visitor_id from adv)),
    'opened_listing',  (select count(*) from pv where visitor_id in (select visitor_id from adv)
                          and visitor_id in (select visitor_id from viewers))
  ),
  -- referral loop: who clicked the "invite a friend" button, who shared a link,
  -- and how many friends actually signed up through a link
  'referrals', jsonb_build_object(
    'opened',      (select count(distinct user_id) from public.events
                      where event = 'referral_open' and props->>'via' = 'button'
                        and user_id is not null and user_id <> 'af2629f7-1121-4bee-8a2b-cede9318c864'),
    'shared',      (select count(distinct user_id) from public.events
                      where event = 'referral_share'
                        and user_id is not null and user_id <> 'af2629f7-1121-4bee-8a2b-cede9318c864'),
    'redemptions', (select count(*) from public.referrals where status = 'redeemed')
  ),
  'today', jsonb_build_object(
    'visitors', (select count(distinct visitor_id) from v
                   where (created_at at time zone 'America/New_York')::date
                       = (now() at time zone 'America/New_York')::date),
    'visits',   (select count(*) from v
                   where (created_at at time zone 'America/New_York')::date
                       = (now() at time zone 'America/New_York')::date),
    'new_visitors',       (select count(*) from today_new),
    'new_opened_listing', (select count(*) from today_new t
                             where t.visitor_id in (select visitor_id from openers_today))
  ),
  -- Real revenue only: plan 'plus' WITH a live Stripe subscription, excluding
  -- comped (plan 'comp') accounts and the owner's own test sub. Comps are
  -- surfaced separately so the count is honest but not counted as MRR.
  'subscriptions', jsonb_build_object(
    'paying', (select count(*) from public.subscriptions
                 where status in ('active','trialing') and plan = 'plus'
                   and stripe_subscription_id is not null
                   and user_id <> 'af2629f7-1121-4bee-8a2b-cede9318c864'
                   and (current_period_end is null or current_period_end > now())),
    'comped', (select count(*) from public.subscriptions
                 where status in ('active','trialing') and plan = 'comp'),
    'mrr',    round((select count(*) from public.subscriptions
                 where status in ('active','trialing') and plan = 'plus'
                   and stripe_subscription_id is not null
                   and user_id <> 'af2629f7-1121-4bee-8a2b-cede9318c864'
                   and (current_period_end is null or current_period_end > now())) * 4.99, 2)
  ),
  'sparkline', coalesce((
    select jsonb_agg(jsonb_build_object('date', d, 'views', views, 'visitors', visitors) order by d)
    from days14), '[]'::jsonb),
  'events', coalesce((
    select jsonb_object_agg(event, n) from (select event, count(*) as n from ev group by 1) e),
    '{}'::jsonb)
)
$$;

-- Lock it down: never callable with the public anon/authenticated key.
revoke all on function public.dashboard_metrics() from public, anon, authenticated;
grant execute on function public.dashboard_metrics() to service_role;

notify pgrst, 'reload schema';
