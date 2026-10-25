-- The owner dashboard's Crashes page (2026-10-25): visitors per day by device,
-- the denominator for "how many visitors' pages crashed". Days are New York
-- days. Web visitors by props.dev; the iPhone app (platform ios) separately.
-- Aggregate counts only; service_role (the API) is the only caller.
create or replace function public.dashboard_crash_days(p_since timestamptz)
returns table(d date, iphone int, android int, ipad int, desktop int, app int)
language sql stable security definer set search_path = public as $$
  select (e.created_at at time zone 'America/New_York')::date as d,
         count(distinct e.visitor_id) filter (where e.props->>'dev' = 'iphone' and coalesce(e.props->>'platform', 'web') = 'web')::int,
         count(distinct e.visitor_id) filter (where e.props->>'dev' = 'android' and coalesce(e.props->>'platform', 'web') = 'web')::int,
         count(distinct e.visitor_id) filter (where e.props->>'dev' = 'ipad' and coalesce(e.props->>'platform', 'web') = 'web')::int,
         count(distinct e.visitor_id) filter (where e.props->>'dev' = 'desktop' and coalesce(e.props->>'platform', 'web') = 'web')::int,
         count(distinct e.visitor_id) filter (where e.props->>'platform' = 'ios')::int
    from public.events e
   where e.created_at >= p_since
   group by 1
   order by 1
$$;
revoke execute on function public.dashboard_crash_days(timestamptz) from public, anon, authenticated;
grant execute on function public.dashboard_crash_days(timestamptz) to service_role;
