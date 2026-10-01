-- 2026-10-01 (owner): "keep alerts free on mobile and the website" — reverses
-- 0037's paywall on borough alerts. Every active subscriber gets alerts again,
-- including the ones stored locked since 2026-09-30 (they switch on with the
-- next dispatcher run and get the normal welcome, since welcomed_at is null).
-- grandfathered_at / locked_emailed_at stay as history; nothing reads them.

create or replace function public.alert_sub_unlocked(p_email text)
returns boolean
language sql
stable
security definer
set search_path to 'public'
as $$ select true; $$;
revoke all on function public.alert_sub_unlocked(text) from public, anon, authenticated;
grant execute on function public.alert_sub_unlocked(text) to service_role;

create or replace function public.lottery_alerts_recipients()
 returns table(id uuid, email text, boroughs text[], kinds text[], token uuid, welcomed_at timestamp with time zone, last_sent_at timestamp with time zone, max_rent integer, income integer, created_at timestamp with time zone, sent_count integer, nudged_at timestamp with time zone, digest_off boolean)
 language sql
 security definer
 set search_path to 'public'
as $function$
  select s.id, s.email, s.boroughs, s.kinds, s.token, s.welcomed_at, s.last_sent_at, s.max_rent, s.income,
         s.created_at, s.sent_count, s.nudged_at, s.digest_off
    from lottery_alert_subs s
   where s.unsubscribed_at is null
   order by s.created_at;
$function$;
revoke all on function public.lottery_alerts_recipients() from public, anon, authenticated;
grant execute on function public.lottery_alerts_recipients() to service_role;

-- No sign-up is locked any more, so the "turn on your alerts" email never sends.
create or replace function public.lottery_alerts_locked()
returns table(id uuid, email text, boroughs text[], kinds text[], token uuid, created_at timestamptz)
language sql
security definer
set search_path to 'public'
as $$
  select s.id, s.email, s.boroughs, s.kinds, s.token, s.created_at
    from lottery_alert_subs s
   where false;
$$;
revoke all on function public.lottery_alerts_locked() from public, anon, authenticated;
grant execute on function public.lottery_alerts_locked() to service_role;

notify pgrst, 'reload schema';
