-- dashboard_alert_trend: alert sign-up conversion per New York day, as a
-- 7-day rolling rate, from the day alerts launched (2026-09-03) to today.
-- Owner asked 2026-09-30, the day alerts became Plus for new sign-ups: "I'm
-- assuming alert sign-up % will drop by a lot — track our trends from
-- history to the future."
--
-- Per day d, over the 7 days ending d:
--   visitors  distinct visitors, counted exactly as dashboard_metrics' v_all
--             (owner out, referrer-less crawler hits on SEO pages out, one
--             app_open per launch from App Store builds only)
--   signups   alert sign-ups saved (the Alert sign-up conversion tile's count)
--   on        of those, the ones that actually receive alerts: grandfathered
--             (everything before the change) or the account has Plus
-- Before the change on = signups; after it, the gap is the paywall.
-- Day counts (visitors_day, signups_day, on_day) ride along for the tooltip.
--
-- Applied through the Management API. Execute is service_role only.
create or replace function public.dashboard_alert_trend(p_ios_builds text[] default null,
                                                        p_from date default '2026-09-03')
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
    'on_day',       (select count(*) from subs where subs.d = days.d and subs.is_on)
  ) order by days.d), '[]'::jsonb)
from days
$function$;

revoke all on function public.dashboard_alert_trend(text[], date) from public, anon, authenticated;
grant execute on function public.dashboard_alert_trend(text[], date) to service_role;
notify pgrst, 'reload schema';
