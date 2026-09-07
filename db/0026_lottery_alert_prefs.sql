-- 2026-09-07: let a signed-in subscriber see and edit their alert preferences.
-- Read by api_server.py /alerts/prefs after it has verified the caller's
-- Supabase session and taken the email from it — never from the request body,
-- so this cannot be used to look up someone else's subscription.
create or replace function public.lottery_alerts_prefs(p_email text)
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
  select coalesce(
    (select jsonb_build_object(
        'exists', true,
        'boroughs', to_jsonb(s.boroughs),
        'kinds', to_jsonb(s.kinds),
        'max_rent', s.max_rent,
        'income', s.income,
        'unsubscribed', s.unsubscribed_at is not null,
        'since', s.created_at)
       from lottery_alert_subs s where s.email = lower(trim(p_email))),
    jsonb_build_object('exists', false));
$$;
revoke all on function public.lottery_alerts_prefs(text) from public, anon, authenticated;
grant execute on function public.lottery_alerts_prefs(text) to service_role;
