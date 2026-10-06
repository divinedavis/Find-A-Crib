-- Visitors by window (owner, 2026-10-06: "the visitor page takes long to load,
-- we dont need to load all records at once, always start with the 7 day
-- filter. also give us a 'today' filter"). dashboard_visitors(since) only
-- aggregates events since `since`; first-ever visit comes from an index on
-- (visitor_id, created_at). Replaces the no-argument version from 0049.
create index if not exists events_visitor_idx on public.events (visitor_id, created_at);
drop function if exists public.dashboard_visitors();
-- Visitors page (owner, 2026-10-06: "a visitors page (this includes all people
-- who visited the app/website) with the same columns the Signed up users page
-- has"). One row per visitor_id seen in events — the website and the iPhone
-- app both write one — with the same fields dashboard_users() returns, so the
-- page can share its table. A visitor who ever signed in carries that
-- account's name, alerts and Plus; everyone else is "Visitor <id>".
-- Phone/Last device: the app's own events say iphone/ipad/mac (build 96+);
-- the website sends props.dev from 2026-10-06 — older web visitors show —.
create or replace function public.dashboard_visitors(since timestamptz default null)
returns jsonb
language sql stable security definer
set search_path = public
as $$
  with ev as (
    select visitor_id,
           min(created_at) as first_seen,
           max(created_at) as last_seen,
           bool_or(props->>'platform' = 'ios') as ios_app,
           min(created_at) filter (where props->>'platform' = 'ios') as ios_first_seen,
           max((props->>'build')::int) filter (where props->>'platform' = 'ios' and props->>'build' ~ '^[0-9]+$') as ios_build,
           (array_agg(props->>'platform' order by created_at desc))[1] as last_platform,
           (array_agg(coalesce(props->>'dev', props->>'device') order by created_at desc)
              filter (where coalesce(props->>'dev', props->>'device') is not null))[1] as last_dev,
           (array_agg(coalesce(props->>'dev', props->>'device') order by created_at desc)
              filter (where coalesce(props->>'dev', props->>'device') in ('iphone','android')))[1] as phone,
           (array_agg(user_id order by created_at desc) filter (where user_id is not null))[1] as uid,
           count(*) as events
      from public.events
     where visitor_id is not null
       and (since is null or created_at >= since)
     group by visitor_id
  )
  select coalesce(jsonb_agg(v order by v.last_seen desc), '[]'::jsonb) from (
    select
      ev.visitor_id,
      coalesce(nullif(trim(au.raw_user_meta_data->>'full_name'), ''),
               nullif(trim(au.raw_user_meta_data->>'name'), ''),
               split_part(au.email, '@', 1),
               'Visitor ' || left(ev.visitor_id, 6)) as name,
      au.email,
      (au.id is not null) as signed_up,
      -- first visit ever, not first in the window (index events_visitor_idx)
      (select min(e2.created_at) from public.events e2 where e2.visitor_id = ev.visitor_id) as created_at,
      ev.last_seen,
      ev.events,
      case when ev.last_platform = 'ios' then 'app'
           when ev.last_dev in ('iphone','android','ipad','mobile') then 'mobile_web'
           when ev.last_dev = 'desktop' then 'desktop' end as device,
      ev.phone,
      ev.ios_app,
      ev.ios_first_seen,
      ev.ios_build,
      case when ev.last_platform = 'ios' and ev.last_dev in ('iphone','ipad','mac') then ev.last_dev end as app_device,
      (au.id is not null and (
         exists (select 1 from public.lottery_alert_subs l where lower(l.email) = lower(au.email) and l.unsubscribed_at is null)
         or (exists (select 1 from public.saved_buildings sb where sb.user_id = au.id)
             and not exists (select 1 from public.alert_prefs ap where ap.user_id = au.id and ap.unsubscribed_at is not null)))) as alerts,
      (select case when s.plan = 'plus' and (s.stripe_subscription_id is not null or s.provider = 'apple') then 'plus'
                   when s.plan in ('comp','referral','founding') then s.plan end
         from public.subscriptions s
        where s.user_id = au.id and s.status in ('active','trialing')
        order by (s.plan = 'plus') desc limit 1) as plan
    from ev
    left join auth.users au on au.id = ev.uid
    where ev.uid is null or ev.uid not in (select public.dashboard_excluded_ids())
  ) v;
$$;
revoke all on function public.dashboard_visitors(timestamptz) from public, anon, authenticated;
grant execute on function public.dashboard_visitors(timestamptz) to service_role;
