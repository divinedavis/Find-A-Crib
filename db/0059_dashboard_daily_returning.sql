-- dashboard_daily_series: adds 'returning' per day (owner, 2026-10-08: a
-- dotted blue "return users" line on the dashboard's Visitors and sign-ups
-- over time chart). Body otherwise identical to the live definition
-- (db/0046), pulled with pg_get_functiondef before this change.
CREATE OR REPLACE FUNCTION public.dashboard_daily_series(p_ios_builds text[] DEFAULT NULL::text[])
 RETURNS jsonb
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
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
    where au.id not in (select public.dashboard_excluded_ids())
      and au.id in (select user_id from fac_users)
  ),
  today as (select (now() at time zone 'America/New_York')::date as d),
  days as (
    select generate_series('2026-06-24'::date, (select d from today), interval '1 day')::date as d
  ),
  vday as (select d, count(*) as n from vd group by d),
  -- Returning that day = seen that day AND on an earlier day, the same rule
  -- as dashboard_metrics' 'returning' (db/0046), one row per visitor per day.
  firstd as (select visitor_id, min(d) as fd from vd group by visitor_id),
  rday as (select vd.d, count(*) as n from vd join firstd using (visitor_id)
           where vd.d > firstd.fd group by vd.d),
  aday as (select d, count(*) as n from acct group by d),
  periods as (select unnest(array[7, 30, 90]) as n)
select jsonb_build_object(
  'days', coalesce((
    select jsonb_agg(jsonb_build_object(
      'date', to_char(days.d, 'YYYY-MM-DD'),
      'visitors', coalesce(vday.n, 0),
      'signups', coalesce(aday.n, 0),
      'returning', coalesce(rday.n, 0)) order by days.d)
    from days left join vday using (d) left join aday using (d) left join rday using (d)), '[]'::jsonb),
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
