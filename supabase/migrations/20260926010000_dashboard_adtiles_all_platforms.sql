-- "Served impressions" on the Advertiser metrics card counted the website
-- only: tile_served is a web event, and the iPhone app — which logs its
-- re-rental tiles as tile_impression when it draws them, once per apartment
-- per launch — never reached it. The owner asked for every impression on
-- every platform (2026-09-25), so:
--   * served (per agent, per kind) = web tile_served + iPhone tile_impression;
--     the served-window edge (first_served) stays the web event's, so the
--     click-rate window does not stretch back over clicks the web never
--     counted served impressions for;
--   * served_web / served_app split it for the card;
--   * google_ads counts Google's own impressions — AdSense on the website,
--     AdMob in the app — live only, TestFlight's test ads beside, not in.
-- Everything else is pg_get_functiondef() of the live function, unchanged.

CREATE OR REPLACE FUNCTION public.dashboard_adtiles(p_since timestamp with time zone DEFAULT NULL::timestamp with time zone, p_exclude text[] DEFAULT '{}'::text[])
 RETURNS jsonb
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
with r as (
  select event, props, visitor_id, created_at
  from public.events
  where event in ('tile_impression', 'tile_served', 'featured_click', 'hc_click')
    and (p_since is null or created_at >= p_since)
    and (visitor_id is null or visitor_id <> all (coalesce(p_exclude, '{}')))
),
edges as (
  select min(created_at) filter (where event = 'tile_impression') as first_impr,
         min(created_at) filter (where event = 'tile_served')     as first_served
  from r
),
t as (
  select r.*,
         case when event in ('tile_impression', 'tile_served')
                   then coalesce(nullif(props->>'kind', ''), 'rerental')
              when event = 'hc_click' then 'lottery'
              else 'rerental' end as kind,
         case when event = 'hc_click' then 'NYC Housing Connect'
              else coalesce(nullif(props->>'agent', ''), '—') end as agent,
         case when event = 'tile_impression' then 'impressions'
              when event = 'tile_served' then 'served'
              else 'clicks' end as field
  from r
),
per_agent as (
  select agent,
         (array_agg(kind order by created_at desc))[1] as kind,
         count(*) filter (where field = 'impressions') as impressions,
         count(*) filter (where field = 'served' or (event = 'tile_impression' and props->>'platform' = 'ios')) as served,
         count(*) filter (where field = 'clicks') as clicks,
         count(*) filter (where field = 'clicks' and created_at >= e.first_impr) as clicks_measured,
         count(*) filter (where field = 'clicks' and created_at >= e.first_served) as clicks_served,
         count(*) filter (where event = 'featured_click' and props->>'platform' = 'ios') as clicks_ios,
         count(distinct nullif(visitor_id, '')) as reach,
         count(distinct nullif(props->>'addr', '')) as units
  from t, edges e
  group by agent
),
per_kind as (
  select kind,
         count(*) filter (where field = 'impressions') as impressions,
         count(*) filter (where field = 'served' or (event = 'tile_impression' and props->>'platform' = 'ios')) as served,
         count(*) filter (where field = 'clicks') as clicks,
         count(*) filter (where field = 'clicks' and created_at >= e.first_impr) as clicks_measured,
         count(*) filter (where field = 'clicks' and created_at >= e.first_served) as clicks_served,
         count(distinct nullif(visitor_id, '')) as reach
  from t, edges e
  group by kind
),
clicks as (
  select props from r where event = 'featured_click'
),
platforms as (
  select coalesce(nullif(props->>'platform', ''), 'web') as platform, count(*) as n
  from clicks group by 1
),
-- api_server._source(), line for line: the session's touch the site records
-- on every event since 2026-09-16, else the referrer host, else an ad click
-- id, else direct. Older rows carry none of it and are named, not guessed.
sources as (
  select case
           when props->>'platform' = 'ios' then 'iPhone app'
           when jsonb_typeof(props->'touch') is distinct from 'object' then 'unknown (before 9/16)'
           when coalesce(props->'touch'->>'source', '') <> ''
             then (props->'touch'->>'source')
                  || case when coalesce(props->'touch'->>'medium', '') <> ''
                          then '/' || (props->'touch'->>'medium') else '' end
           when coalesce(props->'touch'->>'src', '') <> '' then 'own link: ' || (props->'touch'->>'src')
           when props->'touch'->>'click' = 'gclid' then 'google ads'
           when coalesce(props->'touch'->>'ref', '') <> '' then props->'touch'->>'ref'
           else 'direct' end as source,
         count(*) as n
  from clicks group by 1
),
-- Every ad impression Google served: the website's AdSense in-feed tiles
-- (index.html settleAds logs ad_impression when a slot fills) and the
-- iPhone's AdMob feed rectangles (Ads.swift). TestFlight's mode=test rows are
-- Google's sample ads — reported, never counted as inventory.
google as (
  select count(*) filter (where coalesce(props->>'mode', '') = 'live' and coalesce(props->>'platform', 'web') <> 'ios') as web,
         count(*) filter (where coalesce(props->>'mode', '') = 'live' and props->>'platform' = 'ios') as app,
         count(*) filter (where coalesce(props->>'mode', '') <> 'live') as test
  from public.events
  where event = 'ad_impression'
    and (p_since is null or created_at >= p_since)
    and (visitor_id is null or visitor_id <> all (coalesce(p_exclude, '{}')))
),
boros as (
  select props->>'boro' as borough, count(*) as n
  from clicks where coalesce(props->>'boro', '') <> '' group by 1
)
select jsonb_build_object(
  'agents', (select coalesce(jsonb_agg(to_jsonb(a)), '[]'::jsonb) from per_agent a),
  'kinds',  (select coalesce(jsonb_agg(to_jsonb(k)), '[]'::jsonb) from per_kind k),
  'reach',  (select count(distinct nullif(visitor_id, '')) from r),
  'first_impression', (select first_impr from edges),
  'first_served',     (select first_served from edges),
  'served_web',       (select count(*) from r where event = 'tile_served'),
  'served_app',       (select count(*) from r where event = 'tile_impression' and props->>'platform' = 'ios'),
  'google_ads',       (select to_jsonb(g) from google g),
  'click_platforms',  (select coalesce(jsonb_object_agg(platform, n), '{}'::jsonb) from platforms),
  'click_sources',    (select coalesce(jsonb_agg(jsonb_build_object('source', source, 'clicks', n)
                                                 order by n desc, source), '[]'::jsonb) from sources),
  'click_boroughs',   (select coalesce(jsonb_agg(jsonb_build_object('borough', borough, 'clicks', n)
                                                 order by n desc, borough), '[]'::jsonb) from boros)
);
$function$;

revoke all on function public.dashboard_adtiles(timestamptz, text[]) from public, anon, authenticated;
grant execute on function public.dashboard_adtiles(timestamptz, text[]) to service_role;
