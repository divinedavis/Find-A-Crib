-- Add "last device" (mobile / tablet / desktop) to the owner user roster.
--
-- Neither public.visits nor public.events records a user agent, so there is no
-- device signal in the product tables at all. GoTrue, however, stamps
-- auth.sessions.user_agent on every sign-in, and that row survives until the
-- session is signed out or its refresh token expires — which covers all 29
-- current users, so the column is populated retroactively rather than only
-- from today forward.
--
-- Caveat worth knowing before reading the column as gospel: this is the device
-- of the newest *session*, not of the last visit in `last_seen` (which comes
-- from visits/events). They agree for anyone who uses one device, and diverge
-- for someone who signed in on a phone and later browsed on a laptop that
-- still holds an older session. It is also blind to iPadOS "Request Desktop
-- Site", which sends a Macintosh UA and therefore reads as desktop.

create or replace function public.dashboard_users()
returns jsonb
language sql
security definer
set search_path = public
as $$
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
      -- device of the most recently active session. refreshed_at is null until
      -- the first token refresh, so fall back through updated_at to created_at
      -- rather than letting a null sort a fresh session to the bottom.
      (select case
                when s.user_agent ilike '%ipad%'
                  or (s.user_agent ilike '%android%' and s.user_agent not ilike '%mobile%')
                  then 'tablet'
                when s.user_agent ilike '%iphone%'
                  or s.user_agent ilike '%android%'
                  or s.user_agent ilike '%mobile%'
                  then 'mobile'
                when s.user_agent is null or trim(s.user_agent) = '' then null
                else 'desktop'
              end
         from auth.sessions s
        where s.user_id = au.id
        order by coalesce(s.refreshed_at, s.updated_at, s.created_at) desc
        limit 1) as device,
      (select count(*) from public.saved_buildings sb where sb.user_id = au.id) as saves,
      -- referral links this user has shared (copy / native-share actions)
      (select count(*) from public.events e where e.user_id = au.id and e.event = 'referral_share') as shares,
      -- paying Plus / comped / (null = free)
      (select case when s.plan = 'plus' and s.stripe_subscription_id is not null then 'plus'
                   when s.plan = 'comp' then 'comp'
                   when s.plan = 'referral' then 'referral' end
         from public.subscriptions s
        where s.user_id = au.id and s.status in ('active', 'trialing')
        order by (s.plan = 'plus') desc, (s.plan = 'referral') desc limit 1) as plan,
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
        exists (select 1 from public.saved_searches  x where x.user_id = au.id)
      )
  ) u;
$$;

revoke all on function public.dashboard_users() from public, anon, authenticated;
grant execute on function public.dashboard_users() to service_role;

notify pgrst, 'reload schema';
