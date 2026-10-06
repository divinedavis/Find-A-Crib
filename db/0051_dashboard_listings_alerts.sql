-- Listings & alerts page (owner, 2026-10-06: "can we track how many people are
-- viewing a specific listing or alert and who is getting alerts for which
-- borough"). Two owner-only functions behind /dashboard-listings.

-- Per re-rental / lottery listing since `since`: people who saw its tile
-- (tile_impression), people who opened it (featured_click / hc_click), and
-- people who opened it from an alert push (push_item_open — keyed by the
-- listing's link; the API maps links to listings). Website and app alike.
create or replace function public.dashboard_listings(since timestamptz)
returns jsonb
language sql stable security definer
set search_path = public
as $$
  with ev as (
    select event, visitor_id, props from public.events
     where created_at >= since
       and event in ('tile_impression', 'featured_click', 'hc_click', 'push_item_open')
  ), tiles as (
    select props->>'addr' as addr,
           max(props->>'kind') as kind, max(props->>'agent') as agent, max(props->>'boro') as boro,
           count(distinct visitor_id) filter (where event = 'tile_impression') as saw,
           count(distinct visitor_id) filter (where event in ('featured_click', 'hc_click')) as opened
      from ev where event <> 'push_item_open' and coalesce(props->>'addr', '') <> ''
     group by 1
  ), pushes as (
    select props->>'url' as url, max(props->>'kind') as kind,
           count(distinct visitor_id) as alert_opens
      from ev where event = 'push_item_open' and coalesce(props->>'url', '') <> ''
     group by 1
  )
  select jsonb_build_object(
    'tiles', coalesce((select jsonb_agg(t order by t.saw desc) from tiles t), '[]'::jsonb),
    'pushes', coalesce((select jsonb_agg(p order by p.alert_opens desc) from pushes p), '[]'::jsonb));
$$;

-- Who is getting borough alerts: every active subscription (email or the
-- app's push, both live in lottery_alert_subs) with boroughs, kinds, when it
-- started, how many alerts it has been sent and when the last one went.
-- Income is deliberately left out.
create or replace function public.dashboard_alert_subs()
returns jsonb
language sql stable security definer
set search_path = public
as $$
  select coalesce(jsonb_agg(jsonb_build_object(
           'email', s.email, 'boroughs', s.boroughs, 'kinds', s.kinds,
           'created_at', s.created_at, 'last_sent_at', s.last_sent_at, 'sent_count', s.sent_count,
           'household_size', s.household_size,
           'name', coalesce(nullif(trim(u.raw_user_meta_data->>'full_name'), ''), nullif(trim(u.raw_user_meta_data->>'name'), ''))
         ) order by s.created_at desc), '[]'::jsonb)
    from public.lottery_alert_subs s
    left join auth.users u on lower(u.email) = lower(s.email)
   where s.unsubscribed_at is null
     and (u.id is null or u.id not in (select public.dashboard_excluded_ids()));
$$;

revoke all on function public.dashboard_listings(timestamptz) from public, anon, authenticated;
revoke all on function public.dashboard_alert_subs() from public, anon, authenticated;
grant execute on function public.dashboard_listings(timestamptz) to service_role;
grant execute on function public.dashboard_alert_subs() to service_role;
