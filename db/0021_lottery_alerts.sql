-- Borough alerts: "email me the minute a new housing lottery or re-rental
-- opens in <borough>". Public sign-up, no account required.
--
-- Written only through the findacrib-api (service role) and read only by the
-- lottery_alerts.py dispatcher on the droplet (service role). RLS is on with
-- NO anon/authenticated policies or grants on purpose — an email list is the
-- last thing that should be readable through the Data API, and every new
-- function is also revoked from public/anon explicitly because Supabase
-- grants anon EXECUTE on every new function by default.
--
-- One row per email. Re-subscribing updates the boroughs and clears
-- unsubscribed_at, so the form doubles as "change my boroughs".

create table if not exists public.lottery_alert_subs (
  id              uuid primary key default gen_random_uuid(),
  email           text not null unique,
  boroughs        text[] not null,
  kinds           text[] not null default '{lottery,rerental}',
  token           uuid not null unique default gen_random_uuid(),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  welcomed_at     timestamptz,
  unsubscribed_at timestamptz,
  last_sent_at    timestamptz,
  sent_count      int not null default 0,
  constraint lottery_alert_subs_email_ck
    check (email = lower(email) and length(email) between 6 and 254
           and email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'),
  constraint lottery_alert_subs_boroughs_ck
    check (cardinality(boroughs) between 1 and 5
           and boroughs <@ array['M','Bk','Q','Bx','SI']::text[]),
  constraint lottery_alert_subs_kinds_ck
    check (cardinality(kinds) between 1 and 2
           and kinds <@ array['lottery','rerental']::text[])
);
alter table public.lottery_alert_subs enable row level security;
revoke all on public.lottery_alert_subs from public, anon, authenticated;
grant select, insert, update, delete on public.lottery_alert_subs to service_role;

-- Sign up / update. The API rate-limits per IP before calling this; the daily
-- ceiling here is the backstop against an IP-rotating signup flood filling the
-- table (and the sender's hourly SMTP budget) overnight.
create or replace function public.lottery_alerts_subscribe(
  p_email text, p_boroughs text[], p_kinds text[] default '{lottery,rerental}')
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_email text := lower(trim(p_email));
  v_boros text[];
  v_kinds text[];
  v_today int;
  v_row lottery_alert_subs;
begin
  select array_agg(distinct b) into v_boros
    from unnest(p_boroughs) b where b = any(array['M','Bk','Q','Bx','SI']);
  select array_agg(distinct k) into v_kinds
    from unnest(coalesce(p_kinds, '{lottery,rerental}')) k
    where k = any(array['lottery','rerental']);
  if v_boros is null then
    return jsonb_build_object('ok', false, 'reason', 'no_borough');
  end if;
  if v_kinds is null then
    v_kinds := '{lottery,rerental}';
  end if;
  if v_email !~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$' or length(v_email) > 254 then
    return jsonb_build_object('ok', false, 'reason', 'invalid_email');
  end if;
  select count(*) into v_today from lottery_alert_subs where created_at >= current_date;
  if v_today >= 1000 and not exists (select 1 from lottery_alert_subs where email = v_email) then
    return jsonb_build_object('ok', false, 'reason', 'signup_cap');
  end if;

  insert into lottery_alert_subs (email, boroughs, kinds)
  values (v_email, v_boros, v_kinds)
  on conflict (email) do update
     set boroughs = excluded.boroughs,
         kinds = excluded.kinds,
         unsubscribed_at = null,
         updated_at = now()
  returning * into v_row;
  return jsonb_build_object('ok', true, 'boroughs', to_jsonb(v_row.boroughs),
                            'kinds', to_jsonb(v_row.kinds),
                            'welcomed', v_row.welcomed_at is not null);
end;
$$;

-- Unsubscribe by token. Possession of the (unguessable) uuid is the
-- authorization, same as unsubscribe_alerts for the saved-building emails.
create or replace function public.lottery_alerts_unsubscribe(p_token uuid)
returns boolean language sql security definer set search_path = public as $$
  with u as (
    update lottery_alert_subs
       set unsubscribed_at = coalesce(unsubscribed_at, now()), updated_at = now()
     where token = p_token
    returning 1)
  select exists(select 1 from u);
$$;

-- The dispatcher's read: every active subscriber. Unsubscribed rows never
-- leave the database.
create or replace function public.lottery_alerts_recipients()
returns table (id uuid, email text, boroughs text[], kinds text[], token uuid,
               welcomed_at timestamptz, last_sent_at timestamptz)
language sql security definer set search_path = public as $$
  select id, email, boroughs, kinds, token, welcomed_at, last_sent_at
    from lottery_alert_subs
   where unsubscribed_at is null
   order by created_at;
$$;

-- The dispatcher's write-back after a run.
create or replace function public.lottery_alerts_mark(p_sent uuid[], p_welcomed uuid[])
returns void language sql security definer set search_path = public as $$
  update lottery_alert_subs
     set last_sent_at = now(), sent_count = sent_count + 1, updated_at = now()
   where id = any(coalesce(p_sent, '{}'));
  update lottery_alert_subs
     set welcomed_at = coalesce(welcomed_at, now()), updated_at = now()
   where id = any(coalesce(p_welcomed, '{}'));
$$;

revoke all on function public.lottery_alerts_subscribe(text, text[], text[]) from public, anon, authenticated;
revoke all on function public.lottery_alerts_unsubscribe(uuid) from public, anon, authenticated;
revoke all on function public.lottery_alerts_recipients() from public, anon, authenticated;
revoke all on function public.lottery_alerts_mark(uuid[], uuid[]) from public, anon, authenticated;
grant execute on function public.lottery_alerts_subscribe(text, text[], text[]) to service_role;
grant execute on function public.lottery_alerts_unsubscribe(uuid) to service_role;
grant execute on function public.lottery_alerts_recipients() to service_role;
grant execute on function public.lottery_alerts_mark(uuid[], uuid[]) to service_role;
