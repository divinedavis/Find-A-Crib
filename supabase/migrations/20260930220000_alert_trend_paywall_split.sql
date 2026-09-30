-- dashboard_alert_trend, extended 2026-09-30 (owner: "show the trend of the
-- people who signed up for alerts before paywall and who signed up after we
-- put alerts behind a paywall"). Adds gf_signups (grandfathered, 7-day
-- window) and post_visitors / post_signups / post_on (window clipped to
-- start on 30 Sep; null before). Existing fields unchanged. Built from the
-- live definition (pg_get_functiondef), not db/0038.
CREATE OR REPLACE FUNCTION public.dashboard_alert_trend(p_ios_builds text[] DEFAULT NULL::text[], p_from date DEFAULT '2026-09-03'::date)
 RETURNS jsonb
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
with
  mine as (
    select visitor_id from public.visits
      where user_id = 'af2629f7-1121-4bee-8a2b-cede9318c864' and visitor_id is not null
    union
    select visitor_id from public.events
      where user_id = 'af2629f7-1121-4bee-8a2b-cede9318c864' and visitor_id is not null
  ),
  lo as (select ((p_from - 7)::timestamp at time zone 'America/New_York') as ts),
  v_all as (
    select visitor_id, created_at from public.visits, lo
    where created_at >= lo.ts
      and user_id is distinct from 'af2629f7-1121-4bee-8a2b-cede9318c864'
      and visitor_id is not null
      and visitor_id not in (select visitor_id from mine)
      and not (coalesce(referrer,'') = '' and (
        path like '/building/%' or path like '/borough/%' or path like '/neighborhood/%'))
    union all
    select e.visitor_id, e.created_at from public.events e, lo
    where e.created_at >= lo.ts
      and e.event = 'app_open'
      and e.props->>'platform' = 'ios'
      and (p_ios_builds is null or e.props->>'build' = any(p_ios_builds))
      and e.user_id is distinct from 'af2629f7-1121-4bee-8a2b-cede9318c864'
      and e.visitor_id is not null
      and e.visitor_id not in (select visitor_id from mine)
  ),
  vd as (
    select distinct visitor_id, (created_at at time zone 'America/New_York')::date as d from v_all
  ),
  subs as (
    select (s.created_at at time zone 'America/New_York')::date as d,
           (s.grandfathered_at is not null) as is_gf,
           (s.grandfathered_at is not null
            or exists (select 1 from auth.users u
                        where lower(u.email) = s.email and public.has_plus(u.id))) as is_on
      from public.lottery_alert_subs s
     where s.email not in (select lower(email) from auth.users
                            where id = 'af2629f7-1121-4bee-8a2b-cede9318c864')
  ),
  days as (
    select generate_series(p_from, (now() at time zone 'America/New_York')::date, interval '1 day')::date as d
  )
select coalesce(jsonb_agg(jsonb_build_object(
    'date',         to_char(days.d, 'YYYY-MM-DD'),
    'visitors',     (select count(distinct visitor_id) from vd where vd.d between days.d - 6 and days.d),
    'signups',      (select count(*) from subs where subs.d between days.d - 6 and days.d),
    'on',           (select count(*) from subs where subs.d between days.d - 6 and days.d and subs.is_on),
    'visitors_day', (select count(*) from vd where vd.d = days.d),
    'signups_day',  (select count(*) from subs where subs.d = days.d),
    'on_day',       (select count(*) from subs where subs.d = days.d and subs.is_on),
    -- Before/after the paywall (db/0039). gf_signups: grandfathered sign-ups
    -- (everyone before 2026-09-30 16:38 UTC) in the 7-day window. post_*:
    -- the window clipped to start no earlier than 30 Sep, so the after-
    -- paywall rates never divide by pre-paywall visitors; null before.
    'gf_signups',   (select count(*) from subs where subs.d between days.d - 6 and days.d and subs.is_gf),
    'post_visitors', case when days.d >= date '2026-09-30' then
                       (select count(distinct visitor_id) from vd
                         where vd.d between greatest(days.d - 6, date '2026-09-30') and days.d) end,
    'post_signups',  case when days.d >= date '2026-09-30' then
                       (select count(*) from subs where not subs.is_gf
                           and subs.d between greatest(days.d - 6, date '2026-09-30') and days.d) end,
    'post_on',       case when days.d >= date '2026-09-30' then
                       (select count(*) from subs where not subs.is_gf and subs.is_on
                           and subs.d between greatest(days.d - 6, date '2026-09-30') and days.d) end
  ) order by days.d), '[]'::jsonb)
from days
$function$;

revoke all on function public.dashboard_alert_trend(text[], date) from public, anon, authenticated;
grant execute on function public.dashboard_alert_trend(text[], date) to service_role;
notify pgrst, 'reload schema';
