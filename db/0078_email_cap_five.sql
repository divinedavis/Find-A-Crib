-- 0078: up to FIVE Find A Crib emails per person per day, was one (0024).
--
-- Owner, 2026-11-17: "lets increase our email limit to 5 a day per user".
-- Same day, after a Plus subscriber's alert was pushed at 10 AM but its email
-- was held for tomorrow: "emails should come in real time for plus users".
-- With one slot a day, any morning email (the 8 AM digest, the saved-building
-- mail, a 2 AM alert) pushed every later real-time alert email to tomorrow.
--
-- email_sends becomes one row per email sent (seq 1..5 within the New York
-- day) instead of one row per day, so dashboard_alert_trend's
-- count(distinct email) where kind = 'alert' still means "people alerted".
-- Concurrent claims for one address are serialised with an advisory lock so
-- two jobs racing for the fifth slot cannot both win it.

alter table public.email_sends add column if not exists seq smallint not null default 1;
alter table public.email_sends drop constraint if exists email_sends_pkey;
alter table public.email_sends add constraint email_sends_pkey primary key (email, day, seq);

create or replace function public.email_claim(p_email text, p_kind text)
returns boolean language plpgsql security definer set search_path = public as $$
declare
  v_email text := lower(trim(p_email));
  v_day   date := (now() at time zone 'America/New_York')::date;
  v_n     int;
begin
  perform pg_advisory_xact_lock(hashtextextended('email_claim:' || v_email, 0));
  select coalesce(max(seq), 0) into v_n
    from email_sends where email = v_email and day = v_day;
  if v_n >= 5 then
    return false;
  end if;
  insert into email_sends (email, day, kind, seq)
  values (v_email, v_day, left(coalesce(p_kind, 'mail'), 40), v_n + 1);
  -- Opportunistic housekeeping: the ledger is a send history, not an archive.
  if random() < 0.02 then
    delete from email_sends where day < v_day - 120;
  end if;
  return true;
end;
$$;

-- Give back the most recent slot when the send itself failed.
create or replace function public.email_release(p_email text)
returns boolean language plpgsql security definer set search_path = public as $$
declare
  v_email text := lower(trim(p_email));
  v_day   date := (now() at time zone 'America/New_York')::date;
begin
  perform pg_advisory_xact_lock(hashtextextended('email_claim:' || v_email, 0));
  delete from email_sends
   where email = v_email and day = v_day
     and seq = (select max(seq) from email_sends where email = v_email and day = v_day);
  return found;
end;
$$;

revoke all on function public.email_claim(text, text) from public, anon, authenticated;
revoke all on function public.email_release(text) from public, anon, authenticated;
grant execute on function public.email_claim(text, text) to service_role;
grant execute on function public.email_release(text) to service_role;
