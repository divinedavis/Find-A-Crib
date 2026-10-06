-- 2026-10-06: the owner (not 62+) was alerted about Luna Green, an HCR senior
-- development ("head of household ... must be 62 years of age or older").
-- Senior-only lotteries now go only to subscribers who say someone in the
-- household is 62 or older.
alter table public.lottery_alert_subs add column if not exists seniors boolean not null default false;

create or replace function public.lottery_alerts_set_seniors(p_email text, p_seniors boolean)
returns void language sql security definer set search_path to 'public' as $$
  update lottery_alert_subs set seniors = coalesce(p_seniors, false), updated_at = now()
   where email = lower(trim(p_email)) and unsubscribed_at is null;
$$;

create or replace function public.lottery_alerts_seniors()
returns setof text language sql stable security definer set search_path to 'public' as $$
  select email from lottery_alert_subs where unsubscribed_at is null and seniors;
$$;

create or replace function public.lottery_alerts_senior(p_email text)
returns boolean language sql stable security definer set search_path to 'public' as $$
  select coalesce((select seniors from lottery_alert_subs where email = lower(trim(p_email)) and unsubscribed_at is null limit 1), false);
$$;

revoke all on function public.lottery_alerts_set_seniors(text, boolean) from public, anon, authenticated;
revoke all on function public.lottery_alerts_seniors() from public, anon, authenticated;
revoke all on function public.lottery_alerts_senior(text) from public, anon, authenticated;
grant execute on function public.lottery_alerts_set_seniors(text, boolean) to service_role;
grant execute on function public.lottery_alerts_seniors() to service_role;
grant execute on function public.lottery_alerts_senior(text) to service_role;
notify pgrst, 'reload schema';
