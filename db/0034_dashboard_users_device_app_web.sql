-- "Last device" could not tell the iPhone APP from a phone BROWSER: 0033 read
-- the app's user agent ("Find%20A%20Crib/<build> CFNetwork/... Darwin/...")
-- and then answered 'mobile', the same word Safari on a phone gets. The owner
-- reads that column to know which front end people are actually using
-- (2026-09-23), so it now answers one of three things:
--
--   app         the iPhone/iPad app  (its own user agent)
--   mobile_web  a browser on a phone or a tablet
--   desktop     a browser on a computer
--   null        no session on record yet
--
-- 'tablet' is gone as a separate answer: an iPad in Safari is mobile web, and
-- an iPad running the app carries the app's user agent, so it reads 'app'
-- exactly like an iPhone does.
--
-- Everything else in this function is unchanged from 0033.
-- Applied to production 2026-09-23 through the Management API SQL endpoint.
create or replace function public.dashboard_users()
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
begin
  perform public.refresh_ios_app_users();
  return (
select coalesce(jsonb_agg(u order by u.created_at desc), '[]'::jsonb)
  from (
    select
      coalesce(nullif(trim(au.raw_user_meta_data->>'full_name'), ''),
               nullif(trim(au.raw_user_meta_data->>'name'), ''),
               split_part(au.email, '@', 1)) as name,
      au.email,
      coalesce(au.raw_app_meta_data->>'provider', 'email') as provider,
      au.created_at,
      -- real "last seen": last_sign_in_at only changes on an explicit re-login,
      -- but returning users come back on a persisted session — so use the latest
      -- signed-in activity from the visit/event logs (greatest() skips nulls)
      greatest(
        au.last_sign_in_at,
        (select max(created_at) from public.visits v where v.user_id = au.id),
        (select max(created_at) from public.events  e where e.user_id = au.id)
      ) as last_seen,
      -- which front end the most recently active session was: the app, a
      -- browser on a phone/tablet, or a browser on a computer. refreshed_at is
      -- null until the first token refresh, so fall back through updated_at to
      -- created_at rather than letting a null sort a fresh session to the bottom.
      (select case
                -- The app signs in as "Find%20A%20Crib/79 CFNetwork/..." — no
                -- "iPhone" anywhere in it, which is why it used to read as a
                -- desktop, and then (0033) as a phone browser.
                when s.user_agent like 'Find%20A%20Crib/%' or s.user_agent like 'Find A Crib/%'
                  then 'app'
                when s.user_agent ilike '%ipad%'
                  or s.user_agent ilike '%iphone%'
                  or s.user_agent ilike '%android%'
                  or s.user_agent ilike '%mobile%'
                  then 'mobile_web'
                when s.user_agent is null or trim(s.user_agent) = '' then null
                else 'desktop'
              end
         from auth.sessions s
        where s.user_id = au.id
        order by coalesce(s.refreshed_at, s.updated_at, s.created_at) desc
        limit 1) as device,
      -- phone OS across all live sessions (newest wins); the iOS app's own UA
      -- and the persisted ios_app_users row both count as iPhone
      coalesce(
        (select case when s.user_agent ilike '%android%' then 'android' else 'iphone' end
           from auth.sessions s
          where s.user_id = au.id
            and (s.user_agent ilike '%android%'
                 or s.user_agent ilike '%iphone%'
                 or s.user_agent like 'Find%20A%20Crib/%'
                 or s.user_agent like 'Find A Crib/%')
          order by coalesce(s.refreshed_at, s.updated_at, s.created_at) desc
          limit 1),
        (select 'iphone' from public.ios_app_users i where i.user_id = au.id)
      ) as phone,
      (select count(*) from public.saved_buildings sb where sb.user_id = au.id) as saves,
      -- referral links this user has shared (copy / native-share actions)
      (select count(*) from public.events e where e.user_id = au.id and e.event = 'referral_share') as shares,
      -- on any alert: borough lottery/re-rental emails (by address, no account
      -- needed) or saved-building emails (every saver, unless switched off)
      (exists (select 1 from public.lottery_alert_subs l
                where lower(l.email) = lower(au.email) and l.unsubscribed_at is null)
       or (exists (select 1 from public.saved_buildings sb where sb.user_id = au.id)
           and not exists (select 1 from public.alert_prefs ap
                            where ap.user_id = au.id and ap.unsubscribed_at is not null))) as alerts,
      -- iPhone app (2026-09-09): ever signed in from the app; persisted in
      -- ios_app_users so an expired session does not un-count them
      (select true from public.ios_app_users i where i.user_id = au.id) as ios_app,
      (select i.first_seen from public.ios_app_users i where i.user_id = au.id) as ios_first_seen,
      (select i.last_build from public.ios_app_users i where i.user_id = au.id) as ios_build,
      -- paying Plus / comped / (null = free)
      (select case when s.plan = 'plus' and (s.stripe_subscription_id is not null or s.provider = 'apple') then 'plus'
                   when s.plan = 'comp' then 'comp'
                   when s.plan = 'referral' then 'referral'
                   when s.plan = 'founding' then 'founding' end
         from public.subscriptions s
        where s.user_id = au.id and s.status in ('active', 'trialing')
        order by (s.plan = 'plus') desc, (s.plan = 'referral') desc, (s.plan = 'comp') desc limit 1) as plan,
      -- "searching in": most-viewed borough from building_view events (props.boro
      -- is a borough code M/Bk/Q/Bx/SI), else the borough of a saved building
      -- (BBL first digit 1-5); the client maps either encoding to a name
      coalesce(
        (select e.props->>'boro' from public.events e
          where e.user_id = au.id and e.event = 'building_view'
            and coalesce(e.props->>'boro', '') <> ''
          group by e.props->>'boro' order by count(*) desc limit 1),
        (select substr(sb.bbl, 1, 1) from public.saved_buildings sb
          where sb.user_id = au.id group by substr(sb.bbl, 1, 1) order by count(*) desc limit 1)
      ) as area_code
    from auth.users au
    where au.id <> 'af2629f7-1121-4bee-8a2b-cede9318c864'
      -- This Supabase project's auth is SHARED (originally Jays Home Finder;
      -- Kinnkolk's family-tree tables still live here). Only count a user as a
      -- Find A Crib user if they left real product activity — otherwise the
      -- roster pulls in Kinnkolk/other-app accounts that never touched the site.
      and (
        exists (select 1 from public.visits          x where x.user_id = au.id) or
        exists (select 1 from public.events          x where x.user_id = au.id) or
        exists (select 1 from public.saved_buildings x where x.user_id = au.id) or
        exists (select 1 from public.subscriptions   x where x.user_id = au.id) or
        exists (select 1 from public.saved_searches  x where x.user_id = au.id) or
        exists (select 1 from public.ios_app_users   x where x.user_id = au.id)
      )
  ) u
  );
end;
$function$;
