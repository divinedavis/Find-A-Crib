-- dashboard_signups_series: Find A Crib accounts created per New York day
-- (last p_days) and per calendar month (last p_months), for the sign-up bars
-- that sit beside the visitor bars on the owner dashboard (2026-09-27).
--
-- "An account" is counted exactly as the Sign-ups tile counts it
-- (dashboard_metrics' acct_all): an auth.users row that has touched Find A
-- Crib (fac_users), owner excluded. auth.users is shared by other products on
-- this project, so an unfiltered count would include their accounts.
--
-- Applied to production through the Management API SQL endpoint. Execute is
-- service_role only, like dashboard_metrics.
CREATE OR REPLACE FUNCTION public.dashboard_signups_series(p_days int DEFAULT 14, p_months int DEFAULT 7)
 RETURNS jsonb
 LANGUAGE sql
 STABLE
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
with
  fac_users as (
    select user_id from public.visits where user_id is not null
    union select user_id from public.events where user_id is not null
    union select user_id from public.saved_buildings
    union select user_id from public.subscriptions
    union select user_id from public.saved_searches
  ),
  acct as (
    select (au.created_at at time zone 'America/New_York') as local_ts
    from auth.users au
    where au.id <> 'af2629f7-1121-4bee-8a2b-cede9318c864'
      and au.id in (select user_id from fac_users)
  ),
  today as (select (now() at time zone 'America/New_York')::date as d)
select jsonb_build_object(
  'days', coalesce((
    select jsonb_object_agg(to_char(d, 'YYYY-MM-DD'), n)
    from (select local_ts::date as d, count(*) as n from acct, today
          where local_ts::date > today.d - greatest(p_days, 1)
          group by 1) x), '{}'::jsonb),
  'months', coalesce((
    select jsonb_object_agg(to_char(m, 'YYYY-MM'), n)
    from (select date_trunc('month', local_ts)::date as m, count(*) as n from acct, today
          where local_ts >= (date_trunc('month', today.d::timestamp)
                             - make_interval(months => greatest(p_months, 1) - 1))
          group by 1) x), '{}'::jsonb)
)
$function$;

revoke all on function public.dashboard_signups_series(int, int) from public, anon, authenticated;
grant execute on function public.dashboard_signups_series(int, int) to service_role;
