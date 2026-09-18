-- Advertiser-tile inventory for the owner dashboard, aggregated where the
-- rows live. api_server._fac_adtiles used to SELECT every ad-tile event
-- through PostgREST and count them in Python: 123,000 rows on 2026-09-18
-- (112,000 of them tile_served, growing ~1,500 a day) in 123 offset-paged
-- requests — each page walking the created_at index from the top — ~25 MB
-- per call, 5.8 s cold, paid on every range flip and once per gunicorn
-- worker. One pass here returns ~5 KB.
--
-- The counting rules are api_server's, moved not changed:
--   * an agent's kind is the kind on its NEWEST row (Python read the rows
--     created_at desc and set it on first sight);
--   * hc_click is always ('lottery', 'NYC Housing Connect'); featured_click
--     is 'rerental' under props.agent; the two tile events carry both in props;
--   * clicks_measured counts clicks at or after the first viewable impression,
--     clicks_served at or after the first served one — the only windows in
--     which a click rate means anything;
--   * reach is distinct non-empty visitor_ids, units distinct props.addr;
--   * the owner's own visitor ids are passed in (p_exclude), decided by
--     _fac_owner_visitors so every card shares one definition of "mine".
-- CTR thresholds, sorting and the served-window age rule stay in Python.
create or replace function public.dashboard_adtiles(p_since timestamptz default null,
                                                    p_exclude text[] default '{}')
returns jsonb
language sql
security definer
set search_path = public
stable
as $$
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
         count(*) filter (where field = 'served') as served,
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
         count(*) filter (where field = 'served') as served,
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
  'click_platforms',  (select coalesce(jsonb_object_agg(platform, n), '{}'::jsonb) from platforms),
  'click_sources',    (select coalesce(jsonb_agg(jsonb_build_object('source', source, 'clicks', n)
                                                 order by n desc, source), '[]'::jsonb) from sources),
  'click_boroughs',   (select coalesce(jsonb_agg(jsonb_build_object('borough', borough, 'clicks', n)
                                                 order by n desc, borough), '[]'::jsonb) from boros)
);
$$;

revoke all on function public.dashboard_adtiles(timestamptz, text[]) from public, anon, authenticated;
grant execute on function public.dashboard_adtiles(timestamptz, text[]) to service_role;

notify pgrst, 'reload schema';
