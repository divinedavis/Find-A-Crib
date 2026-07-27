-- Free-account lifecycle sequence.
--
-- Supabase auth here runs with mailer_autoconfirm and no SMTP host, so a new
-- account currently receives nothing at all — no confirmation, no welcome.
-- This is the plumbing for a short, behaviour-gated sequence that fixes that.
--
-- It reuses alert_prefs (0001_listing_alerts.sql) rather than inventing a
-- second preferences table, but keeps the two opt-outs separate: saved-building
-- alerts are a product feature someone asked for by saving a building, while
-- onboarding mail is not. Collapsing them into one flag would force a user to
-- give up a feature they want in order to stop mail they don't.

alter table public.alert_prefs
  add column if not exists lifecycle_unsubscribed_at timestamptz,
  add column if not exists sent_steps jsonb not null default '[]'::jsonb;

-- Stop only the lifecycle sequence. Mirrors unsubscribe_alerts() so the site
-- can call it with the anon key; the uuid token is the authorization.
create or replace function public.unsubscribe_lifecycle(p_token uuid)
returns boolean
language sql
security definer
set search_path = public
as $$
  update alert_prefs
     set lifecycle_unsubscribed_at = coalesce(lifecycle_unsubscribed_at, now())
   where token = p_token
  returning true;
$$;
revoke all on function public.unsubscribe_lifecycle(uuid) from public;
grant execute on function public.unsubscribe_lifecycle(uuid) to anon, authenticated, service_role;

-- Who is due for a lifecycle email.
--
-- This exists so the growth engine never needs the Supabase management PAT.
-- auth.users is not reachable over PostgREST, and the alternative — shipping a
-- project-wide admin token to the web droplet — would hand anything that reads
-- that droplet full control of the database. This returns the five fields the
-- sequence actually needs and nothing else: no password hash, no tokens beyond
-- the unsubscribe uuid, no provider metadata.
--
-- `since_signup` is deliberately computed here rather than returning raw
-- created_at arithmetic to the caller, so the definition of "day 3" lives in
-- one place.
create or replace function public.lifecycle_accounts_due()
returns table (
  user_id       uuid,
  email         text,
  created_at    timestamptz,
  days_old      int,
  token         uuid,
  sent_steps    jsonb,
  save_count    bigint,
  last_seen     timestamptz
)
language sql
security definer
set search_path = public, auth
as $$
  select u.id,
         u.email::text,
         u.created_at,
         greatest(0, extract(day from (now() - u.created_at))::int),
         p.token,
         coalesce(p.sent_steps, '[]'::jsonb),
         coalesce(s.n, 0),
         v.last_seen
    from auth.users u
    join alert_prefs p on p.user_id = u.id
    left join (select user_id, count(*) n from saved_buildings group by 1) s
           on s.user_id = u.id
    left join (select user_id, max(created_at) last_seen from visits
                where user_id is not null group by 1) v
           on v.user_id = u.id
   where u.email is not null
     and p.unsubscribed_at is null
     and p.lifecycle_unsubscribed_at is null;
$$;
revoke all on function public.lifecycle_accounts_due() from public;
grant execute on function public.lifecycle_accounts_due() to service_role;

-- Record a sent step. Kept as an RPC so the engine needs no write grant on
-- alert_prefs itself.
create or replace function public.lifecycle_mark_sent(p_user_id uuid, p_step text)
returns boolean
language sql
security definer
set search_path = public
as $$
  update alert_prefs
     set sent_steps = coalesce(sent_steps, '[]'::jsonb) || to_jsonb(p_step)
   where user_id = p_user_id
     and not (coalesce(sent_steps, '[]'::jsonb) ? p_step)
  returning true;
$$;
revoke all on function public.lifecycle_mark_sent(uuid, text) from public;
grant execute on function public.lifecycle_mark_sent(uuid, text) to service_role;

-- alert_prefs stays unreadable to anon/authenticated (set in 0001). Restated
-- because the new columns hold opt-out state and send history.
revoke all on public.alert_prefs from anon, authenticated;
grant select, insert, update, delete on public.alert_prefs to service_role;

-- alert_prefs rows are created lazily (notify_saved_listings.py does the same
-- insert), so the sequence must ensure them before it can read anyone.
create or replace function public.lifecycle_ensure_prefs()
returns int
language sql
security definer
set search_path = public, auth
as $$
  with ins as (
    insert into alert_prefs (user_id)
    select u.id from auth.users u
     where not exists (select 1 from alert_prefs p where p.user_id = u.id)
    on conflict (user_id) do nothing
    returning 1
  ) select count(*)::int from ins;
$$;
revoke all on function public.lifecycle_ensure_prefs() from public;
grant execute on function public.lifecycle_ensure_prefs() to service_role;

-- IMPORTANT: revoking from `public` is NOT enough in this project.
--
-- Supabase configures ALTER DEFAULT PRIVILEGES so every new function in the
-- public schema is granted EXECUTE to `anon` and `authenticated` explicitly.
-- A `revoke ... from public` removes only the PUBLIC grant and leaves those
-- role grants in place — which briefly made lifecycle_accounts_due() callable
-- with the browser anon key, returning every user's email address. Any function
-- that must not be public needs an explicit revoke from those two roles.
revoke execute on function public.lifecycle_accounts_due() from anon, authenticated;
revoke execute on function public.lifecycle_ensure_prefs() from anon, authenticated;
revoke execute on function public.lifecycle_mark_sent(uuid, text) from anon, authenticated;
-- unsubscribe_lifecycle deliberately KEEPS anon execute: the site calls it with
-- the anon key, and the unguessable uuid token is the authorization.
