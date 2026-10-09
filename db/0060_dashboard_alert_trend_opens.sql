-- dashboard_alert_trend: adds 'opens_day' — people who clicked an alert email
-- link or tapped an alert push that day (owner, 2026-10-08: "put the alert
-- opens on this chart"). Otherwise identical to the live definition, pulled
-- with pg_get_functiondef before this change.
CREATE OR REPLACE FUNCTION public.dashboard_alert_trend(p_ios_builds text[] DEFAULT NULL::text[], p_from date DEFAULT '2026-09-03'::date)
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
  lo as (select ((p_from - 7)::timestamp at time zone 'America/New_York') as ts),
  v_all as (
    select visitor_id, created_at from public.visits, lo
    where created_at >= lo.ts
      and (user_id is null or user_id not in (select public.dashboard_excluded_ids()))
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
      and (e.user_id is null or e.user_id not in (select public.dashboard_excluded_ids()))
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
                            where id in (select public.dashboard_excluded_ids()))
  ),
  -- Alert opens per day (owner, 2026-10-08), counted as the "Alert opens ·
  -- people who clicked or tapped" tile counts them (dashboard_metrics):
  -- email clickers (distinct subscriber, scanners left out, the owner's own
  -- subscription excluded) plus push tappers (distinct account or visitor,
  -- released builds, the owner's devices excluded). Tagged so the two sides
  -- add up the way the tile adds clickers + push_openers.
  opens as (
    select (c.clicked_at at time zone 'America/New_York')::date as d, 'e:' || c.sub_id::text as who
      from public.alert_clicks c join public.lottery_alert_subs s on s.id = c.sub_id
     where not c.is_bot
       and s.email not in (select lower(email) from auth.users
                            where id in (select public.dashboard_excluded_ids()))
    union
    select (e.created_at at time zone 'America/New_York')::date, 'p:' || coalesce(e.user_id::text, e.visitor_id)
      from public.events e, lo
     where e.created_at >= lo.ts
       and e.event = 'push_open' and e.props->>'platform' = 'ios'
       and (p_ios_builds is null or e.props->>'build' = any(p_ios_builds))
       and (e.user_id is null or e.user_id not in (select public.dashboard_excluded_ids()))
       and e.visitor_id is not null
       and e.visitor_id not in (select visitor_id from mine)
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
    'opens_day',    (select count(distinct who) from opens where opens.d = days.d),
    -- Before/after the paywall (db/0039). gf_signups: grandfathered sign-ups
    -- (everyone before 2026-09-30 16:38 UTC) in the 7-day window. post_*:
    -- the window clipped to start no earlier than 30 Sep, so the after-
    -- paywall rates never divide by pre-paywall visitors; null before.
    'gf_signups',   (select count(*) from subs where subs.d between days.d - 6 and days.d and subs.is_gf),
    -- The paywall was reversed on 1 Oct (db/0042, f0247a3), so post_* stop
    -- there: after it every sign-up is "on" and "paid" means nothing.
    'post_visitors', case when days.d between date '2026-09-30' and date '2026-10-01' then
                       (select count(distinct visitor_id) from vd
                         where vd.d between greatest(days.d - 6, date '2026-09-30') and days.d) end,
    'post_signups',  case when days.d between date '2026-09-30' and date '2026-10-01' then
                       (select count(*) from subs where not subs.is_gf
                           and subs.d between greatest(days.d - 6, date '2026-09-30') and days.d) end,
    'post_on',       case when days.d between date '2026-09-30' and date '2026-10-01' then
                       (select count(*) from subs where not subs.is_gf and subs.is_on
                           and subs.d between greatest(days.d - 6, date '2026-09-30') and days.d) end,
    -- Free again from 2 Oct: the same rate as before the paywall, its window
    -- clipped so it never reaches back into the two paywall days.
    'free_visitors', case when days.d >= date '2026-10-02' then
                       (select count(distinct visitor_id) from vd
                         where vd.d between greatest(days.d - 6, date '2026-10-02') and days.d) end,
    'free_signups',  case when days.d >= date '2026-10-02' then
                       (select count(*) from subs
                         where subs.d between greatest(days.d - 6, date '2026-10-02') and days.d) end
  ) order by days.d), '[]'::jsonb)
from days
$function$;

revoke all on function public.dashboard_alert_trend(text[], date) from public, anon, authenticated;
grant execute on function public.dashboard_alert_trend(text[], date) to service_role;
