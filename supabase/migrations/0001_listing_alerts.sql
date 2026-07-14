-- Saved-building listing alerts ("a building you saved was just advertised").
-- listing_alert_state:  one row per (user, bbl, source) we've already emailed,
--                       so a listing is announced at most once per 60 days.
-- alert_prefs:          per-user unsubscribe token (random uuid — the email
--                       links to findacrib.com/#unsub=<token>).
-- Both tables are written only by the nightly notify_saved_listings.py job via
-- the management API; RLS is on with NO anon/authenticated policies on purpose.

create table if not exists public.listing_alert_state (
  user_id     uuid not null references auth.users(id) on delete cascade,
  bbl         text not null,
  source      text not null check (source in ('zumper', 's8')),
  notified_at timestamptz not null default now(),
  price       int,
  primary key (user_id, bbl, source)
);
alter table public.listing_alert_state enable row level security;
revoke all on public.listing_alert_state from anon, authenticated;
grant select, insert, update, delete on public.listing_alert_state to service_role;

create table if not exists public.alert_prefs (
  user_id         uuid primary key references auth.users(id) on delete cascade,
  token           uuid not null unique default gen_random_uuid(),
  unsubscribed_at timestamptz
);
alter table public.alert_prefs enable row level security;
revoke all on public.alert_prefs from anon, authenticated;
grant select, insert, update, delete on public.alert_prefs to service_role;

-- Unsubscribe-by-token, callable from the site with the anon key. The token is
-- an unguessable uuid, so possession of it is the authorization.
create or replace function public.unsubscribe_alerts(p_token uuid)
returns boolean
language sql
security definer
set search_path = public
as $$
  update alert_prefs
     set unsubscribed_at = coalesce(unsubscribed_at, now())
   where token = p_token
  returning true;
$$;
revoke all on function public.unsubscribe_alerts(uuid) from public;
grant execute on function public.unsubscribe_alerts(uuid) to anon, authenticated, service_role;
