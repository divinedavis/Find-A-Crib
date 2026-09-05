-- 0024: one email a day, saved-building watch for every account, weekly digest.
--
-- Three product decisions (owner, 2026-09-05) land here together because they
-- share plumbing:
--
--   1. Saving a building IS subscribing to it. Every signed-in saver — not only
--      Plus — gets an email when a saved building changes: advertised for rent,
--      a lottery or re-rental opens there, open violations move, a price drops,
--      its DHCR registration changes. (set_alerts_enabled loses its Plus gate;
--      the dispatcher is saved_alerts.py on the web droplet.)
--   2. Nobody gets more than ONE Find A Crib email per calendar day (New York
--      time), whichever job wants to send it. email_sends is the shared ledger
--      every sender must claim a slot in before it sends; a job that loses the
--      slot holds its content for tomorrow instead of dropping it.
--   3. A weekly digest on a fixed day, folded into the same senders and lists,
--      with its own opt-out so stopping it never costs someone the alerts they
--      asked for by saving.
--
-- Everything here is service_role only except the two unsubscribe-by-token
-- functions, which the site calls with the anon key (the unguessable uuid is
-- the authorization — same pattern as unsubscribe_alerts in 0001). Supabase
-- grants anon/authenticated EXECUTE on every new function by default, so each
-- one below is revoked from those roles by name.

-- ---------------------------------------------------------------- 1. ledger

create table if not exists public.email_sends (
  email   text not null,
  day     date not null,
  kind    text not null,
  sent_at timestamptz not null default now(),
  primary key (email, day)
);
alter table public.email_sends enable row level security;
revoke all on public.email_sends from public, anon, authenticated;
grant select, insert, update, delete on public.email_sends to service_role;

-- Claim today's slot for an address. True = this caller may send; false = the
-- address already got (or is about to get) something today. "Today" is the
-- New York calendar day, because that is the day the reader experiences.
create or replace function public.email_claim(p_email text, p_kind text)
returns boolean language plpgsql security definer set search_path = public as $$
declare
  v_day date := (now() at time zone 'America/New_York')::date;
  v_ok boolean;
begin
  insert into email_sends (email, day, kind)
  values (lower(trim(p_email)), v_day, left(coalesce(p_kind, 'mail'), 40))
  on conflict (email, day) do nothing;
  v_ok := found;
  -- Opportunistic housekeeping: the ledger is a send history, not an archive.
  if v_ok and random() < 0.02 then
    delete from email_sends where day < v_day - 120;
  end if;
  return v_ok;
end;
$$;

-- Give a slot back when the send itself failed, so the retry is not blocked
-- by its own claim until tomorrow.
create or replace function public.email_release(p_email text)
returns boolean language sql security definer set search_path = public as $$
  with d as (
    delete from email_sends
     where email = lower(trim(p_email))
       and day = (now() at time zone 'America/New_York')::date
    returning 1)
  select exists(select 1 from d);
$$;

revoke all on function public.email_claim(text, text) from public, anon, authenticated;
revoke all on function public.email_release(text) from public, anon, authenticated;
grant execute on function public.email_claim(text, text) to service_role;
grant execute on function public.email_release(text) to service_role;

-- ------------------------------------------------- 2. saved-building watch

-- Alerts are no longer a Plus feature: enabling them needs an account, nothing
-- more. (Reverses the has_plus check from 0003.)
create or replace function public.set_alerts_enabled(p_on boolean)
returns boolean language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then
    raise exception 'not signed in';
  end if;
  insert into alert_prefs (user_id, unsubscribed_at)
  values (auth.uid(), case when p_on then null else now() end)
  on conflict (user_id) do update set unsubscribed_at = excluded.unsubscribed_at;
  return p_on;
end;
$$;

-- The cooldown table learns the new change kinds. The column was created with
-- an inline check, whose generated name is <table>_<column>_check.
alter table public.listing_alert_state
  drop constraint if exists listing_alert_state_source_check;
alter table public.listing_alert_state
  add constraint listing_alert_state_source_check
  check (source in ('zumper', 's8', 'violations', 'cleared', 'complaints',
                    'rerental', 'lottery', 'price', 'status'));

-- The weekly digest's own opt-out flag (used by saved_watchers below and by
-- unsubscribe_digest in section 3).
alter table public.alert_prefs
  add column if not exists digest_unsubscribed_at timestamptz;

-- Everyone who has saved anything, with what the dispatcher needs to write a
-- personal email and nothing else: no password hash, no provider metadata.
-- `viewed_boros` is the adaptive part of the weekly digest — the boroughs of
-- the buildings this person actually opened in the last 90 days, most recent
-- first — so someone who saved in Brooklyn but has been browsing Queens hears
-- about Queens too.
drop function if exists public.saved_watchers();
create function public.saved_watchers()
returns table (
  user_id       uuid,
  email         text,
  token         uuid,
  created_at    timestamptz,
  alerts_off    boolean,
  digest_off    boolean,
  lifecycle_off boolean,
  sent_steps    jsonb,
  last_seen     timestamptz,
  bbls          text[],
  viewed_boros  text[]
)
language sql security definer set search_path = public, auth as $$
  select u.id,
         u.email::text,
         p.token,
         u.created_at,
         p.unsubscribed_at is not null,
         p.digest_unsubscribed_at is not null,
         p.lifecycle_unsubscribed_at is not null,
         coalesce(p.sent_steps, '[]'::jsonb),
         v.last_seen,
         coalesce(s.bbls, '{}'::text[]),
         coalesce(e.boros, '{}'::text[])
    from auth.users u
    join alert_prefs p on p.user_id = u.id
    left join (select user_id, array_agg(bbl order by created_at desc) bbls
                 from saved_buildings group by 1) s on s.user_id = u.id
    left join (select user_id, max(created_at) last_seen
                 from visits where user_id is not null group by 1) v on v.user_id = u.id
    left join (select user_id, array_agg(boro order by last desc) boros
                 from (select user_id, props->>'boro' boro, max(created_at) last
                         from events
                        where user_id is not null
                          and event = 'building_view'
                          and props->>'boro' in ('M', 'Bk', 'Q', 'Bx', 'SI')
                          and created_at > now() - interval '90 days'
                        group by 1, 2) x
                group by 1) e on e.user_id = u.id
   where u.email is not null
     and u.email not like '%@example.com';
$$;

-- Cooldown read/write for the dispatcher (one announcement per user, building
-- and change kind per window).
create or replace function public.saved_alert_state(p_user_ids uuid[], p_days int default 60)
returns table (user_id uuid, bbl text, source text, notified_at timestamptz)
language sql security definer set search_path = public as $$
  select user_id, bbl, source, notified_at
    from listing_alert_state
   where user_id = any(coalesce(p_user_ids, '{}'))
     and notified_at > now() - make_interval(days => coalesce(p_days, 60));
$$;

create or replace function public.saved_alert_mark(p_rows jsonb)
returns int language plpgsql security definer set search_path = public as $$
declare
  n int;
begin
  insert into listing_alert_state (user_id, bbl, source, price, notified_at)
  select (r->>'user_id')::uuid, r->>'bbl', r->>'source',
         nullif(r->>'price', '')::int, now()
    from jsonb_array_elements(coalesce(p_rows, '[]'::jsonb)) r
   where (r->>'user_id') is not null and (r->>'bbl') ~ '^\d{10}$'
  on conflict (user_id, bbl, source)
  do update set notified_at = now(), price = excluded.price;
  get diagnostics n = row_count;
  return n;
end;
$$;

revoke all on function public.saved_watchers() from public, anon, authenticated;
revoke all on function public.saved_alert_state(uuid[], int) from public, anon, authenticated;
revoke all on function public.saved_alert_mark(jsonb) from public, anon, authenticated;
grant execute on function public.saved_watchers() to service_role;
grant execute on function public.saved_alert_state(uuid[], int) to service_role;
grant execute on function public.saved_alert_mark(jsonb) to service_role;

-- ------------------------------------------------------- 3. weekly digest

-- Stop only the weekly digest. Anon-callable like its two siblings: the site's
-- #unsub handler passes k=digest and the uuid token is the authorization.
create or replace function public.unsubscribe_digest(p_token uuid)
returns boolean language sql security definer set search_path = public as $$
  update alert_prefs
     set digest_unsubscribed_at = coalesce(digest_unsubscribed_at, now())
   where token = p_token
  returning true;
$$;
revoke all on function public.unsubscribe_digest(uuid) from public;
grant execute on function public.unsubscribe_digest(uuid) to anon, authenticated, service_role;

-- Borough-alert subscribers: the first-week nudge needs to know who has never
-- heard from us since the welcome, and the digest needs the sign-up date.
alter table public.lottery_alert_subs
  add column if not exists nudged_at timestamptz,
  add column if not exists digest_off boolean not null default false;

drop function if exists public.lottery_alerts_recipients();
create function public.lottery_alerts_recipients()
returns table (id uuid, email text, boroughs text[], kinds text[], token uuid,
               welcomed_at timestamptz, last_sent_at timestamptz,
               max_rent int, income int,
               created_at timestamptz, sent_count int, nudged_at timestamptz,
               digest_off boolean)
language sql security definer set search_path = public as $$
  select id, email, boroughs, kinds, token, welcomed_at, last_sent_at, max_rent, income,
         created_at, sent_count, nudged_at, digest_off
    from lottery_alert_subs
   where unsubscribed_at is null
   order by created_at;
$$;

drop function if exists public.lottery_alerts_mark(uuid[], uuid[]);
create function public.lottery_alerts_mark(p_sent uuid[], p_welcomed uuid[],
                                            p_nudged uuid[] default null)
returns void language sql security definer set search_path = public as $$
  update lottery_alert_subs
     set last_sent_at = now(), sent_count = sent_count + 1, updated_at = now()
   where id = any(coalesce(p_sent, '{}'));
  update lottery_alert_subs
     set welcomed_at = coalesce(welcomed_at, now()), updated_at = now()
   where id = any(coalesce(p_welcomed, '{}'));
  update lottery_alert_subs
     set nudged_at = coalesce(nudged_at, now()), updated_at = now()
   where id = any(coalesce(p_nudged, '{}'));
$$;

-- A borough subscriber opting out of the digest only (the email's second
-- link). Token-authorised, service_role only: the API endpoint fronts it.
create or replace function public.lottery_alerts_digest_off(p_token uuid)
returns boolean language sql security definer set search_path = public as $$
  with u as (
    update lottery_alert_subs set digest_off = true, updated_at = now()
     where token = p_token
    returning 1)
  select exists(select 1 from u);
$$;

revoke all on function public.lottery_alerts_recipients() from public, anon, authenticated;
revoke all on function public.lottery_alerts_mark(uuid[], uuid[], uuid[]) from public, anon, authenticated;
revoke all on function public.lottery_alerts_digest_off(uuid) from public, anon, authenticated;
grant execute on function public.lottery_alerts_recipients() to service_role;
grant execute on function public.lottery_alerts_mark(uuid[], uuid[], uuid[]) to service_role;
grant execute on function public.lottery_alerts_digest_off(uuid) to service_role;
