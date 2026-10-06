-- Real-time alerts are a Plus feature (owner, 2026-10-06: "users who pay 4.99
-- can get real time alerts. if a user doesnt pay for this they get alerts once
-- a day at 8AM"). lottery_alerts.py asks, per run, which subscriber addresses
-- belong to an account with Plus (has_plus: paying, trial, comp, referral or
-- founding — anyone the app treats as Plus).
create or replace function public.plus_emails(p_emails text[])
returns setof text
language sql stable security definer
set search_path = public
as $$
  select lower(u.email) from auth.users u
   where lower(u.email) = any (select lower(e) from unnest(p_emails) e)
     and public.has_plus(u.id);
$$;
revoke all on function public.plus_emails(text[]) from public, anon, authenticated;
grant execute on function public.plus_emails(text[]) to service_role;
