-- dashboard_daily_series: Find A Crib unique visitors and sign-ups per New
-- York day since tracking began (2026-06-24), plus distinct-visitor totals
-- for the period picker (owner, 2026-09-30: the visitors card "should have a
-- chart with date filters like Alert sign-ups over time").
--
-- visitors: distinct per day, counted exactly as dashboard_metrics' v_all
--           (owner out, referrer-less crawler hits on SEO pages out, one
--           app_open per launch from App Store builds only) — same CTEs as
--           dashboard_alert_trend (db/0038/0039).
-- signups:  Find A Crib accounts created that day, counted as
--           dashboard_signups_series' acct (the Sign-ups tile).
-- periods:  for 7 / 30 / 90 days ending today and the equal period before,
--           DISTINCT visitors (a sum of daily uniques would double-count)
--           and sign-ups; 'all' = since 2026-06-24.
--
-- Applied through the Management API. Execute is service_role only.
create or replace function public.dashboard_daily_series(p_ios_builds text[] default null)
returns jsonb
language sql
stable
security definer
set search_path to 'public'
as $function$
with
  mine as (
    select visitor_id from public.visits
      where user_id = 'af2629f7-1121-4bee-8a2b-cede9318c864' and visitor_id is not null
    union
    select visitor_id from public.events
      where user_id = 'af2629f7-1121-4bee-8a2b-cede9318c864' and visitor_id is not null
  ),
  v_all as (
    select visitor_id, created_at from public.visits
    where user_id is distinct from 'af2629f7-1121-4bee-8a2b-cede9318c864'
      and visitor_id is not null
      and visitor_id not in (select visitor_id from mine)
      and not (coalesce(referrer,'') = '' and (
        path like '/building/%' or path like '/borough/%' or path like '/neighborhood/%'))
    union all
    select e.visitor_id, e.created_at from public.events e
    where e.event = 'app_open'
      and e.props->>'platform' = 'ios'
      and (p_ios_builds is null or e.props->>'build' = any(p_ios_builds))
      and e.user_id is distinct from 'af2629f7-1121-4bee-8a2b-cede9318c864'
      and e.visitor_id is not null
      and e.visitor_id not in (select visitor_id from mine)
  ),
  vd as (
    select distinct visitor_id, (created_at at time zone 'America/New_York')::date as d from v_all
  ),
  fac_users as (
    select user_id from public.visits where user_id is not null
    union select user_id from public.events where user_id is not null
    union select user_id from public.saved_buildings
    union select user_id from public.subscriptions
    union select user_id from public.saved_searches
  ),
  acct as (
    select (au.created_at at time zone 'America/New_York')::date as d
    from auth.users au
    where au.id <> 'af2629f7-1121-4bee-8a2b-cede9318c864'
      and au.id in (select user_id from fac_users)
  ),
  today as (select (now() at time zone 'America/New_York')::date as d),
  days as (
    select generate_series('2026-06-24'::date, (select d from today), interval '1 day')::date as d
  ),
  vday as (select d, count(*) as n from vd group by d),
  aday as (select d, count(*) as n from acct group by d),
  periods as (select unnest(array[7, 30, 90]) as n)
select jsonb_build_object(
  'days', coalesce((
    select jsonb_agg(jsonb_build_object(
      'date', to_char(days.d, 'YYYY-MM-DD'),
      'visitors', coalesce(vday.n, 0),
      'signups', coalesce(aday.n, 0)) order by days.d)
    from days left join vday using (d) left join aday using (d)), '[]'::jsonb),
  'periods', (
    select jsonb_object_agg(periods.n::text, jsonb_build_object(
      'visitors',      (select count(distinct visitor_id) from vd, today
                         where vd.d > today.d - periods.n and vd.d <= today.d),
      'prev_visitors', (select count(distinct visitor_id) from vd, today
                         where vd.d > today.d - 2 * periods.n and vd.d <= today.d - periods.n),
      'signups',       (select count(*) from acct, today
                         where acct.d > today.d - periods.n and acct.d <= today.d),
      'prev_signups',  (select count(*) from acct, today
                         where acct.d > today.d - 2 * periods.n and acct.d <= today.d - periods.n)))
    from periods)
  || jsonb_build_object('all', jsonb_build_object(
      'visitors', (select count(distinct visitor_id) from vd where vd.d >= '2026-06-24'),
      'signups',  (select count(*) from acct where acct.d >= '2026-06-24')))
)
$function$;

revoke all on function public.dashboard_daily_series(text[]) from public, anon, authenticated;
grant execute on function public.dashboard_daily_series(text[]) to service_role;
notify pgrst, 'reload schema';
