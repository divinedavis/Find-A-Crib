-- In-app "Turn off alerts" (owner, 2026-10-12: a Plus member with alerts on
-- should see "Change alerts" and "Turn off alerts", nothing else). The API
-- calls this with the verified session email only — never an email from the
-- request — so a signed-in user can turn off only their own alerts.
create or replace function public.lottery_alerts_unsubscribe_email(p_email text)
returns boolean
language sql
security definer
set search_path = public
as $$
  with u as (
    update lottery_alert_subs
       set unsubscribed_at = coalesce(unsubscribed_at, now()), updated_at = now()
     where email = lower(trim(p_email))
    returning 1)
  select exists(select 1 from u);
$$;
revoke all on function public.lottery_alerts_unsubscribe_email(text) from public, anon, authenticated;
grant execute on function public.lottery_alerts_unsubscribe_email(text) to service_role;
