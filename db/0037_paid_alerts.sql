-- 2026-09-30 (owner): borough alerts become a Find A Crib Plus feature for new
-- sign-ups. Everyone subscribed today keeps them free, forever: their row is
-- stamped grandfathered_at and nothing below ever asks them for money.
--
-- A new sign-up without Plus is still STORED (so paying later just switches
-- it on — no second form), but the dispatcher does not send to it. It gets one
-- "unlock your alerts" email instead (locked_emailed_at), which is also how an
-- iPhone on an older build — that only knows "alerts are on" — finds out.
--
-- Built from the live definitions (pg_get_functiondef, 2026-09-30), not the
-- older migration files.

alter table public.lottery_alert_subs
  add column if not exists grandfathered_at timestamptz,
  add column if not exists locked_emailed_at timestamptz;

update public.lottery_alert_subs
   set grandfathered_at = now()
 where unsubscribed_at is null and grandfathered_at is null
   -- Fixed cutoff (first applied 2026-09-30 16:37 UTC) so re-running this
   -- file can never grandfather a sign-up made after the change.
   and created_at < '2026-09-30 16:38:00+00';

-- Does this address get alerts? Grandfathered, or the account behind the
-- address has Plus (comp / founding / referral count, as has_plus says).
create or replace function public.alert_sub_unlocked(p_email text)
returns boolean
language sql
stable
security definer
set search_path to 'public'
as $$
  select exists (select 1 from public.lottery_alert_subs s
                  where s.email = lower(trim(p_email)) and s.grandfathered_at is not null)
      or exists (select 1 from auth.users u
                  where lower(u.email) = lower(trim(p_email)) and public.has_plus(u.id));
$$;
revoke all on function public.alert_sub_unlocked(text) from public, anon, authenticated;
grant execute on function public.alert_sub_unlocked(text) to service_role;

-- Recipients: unchanged shape, now only unlocked rows. Every sender (alerts,
-- welcome, nudge, weekly, push) reads this one function, so this is the gate.
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
     and (s.grandfathered_at is not null
          or exists (select 1 from auth.users u
                      where lower(u.email) = s.email and public.has_plus(u.id)))
   order by s.created_at;
$function$;
revoke all on function public.lottery_alerts_recipients() from public, anon, authenticated;
grant execute on function public.lottery_alerts_recipients() to service_role;

-- Locked sign-ups that have not had their one "unlock" email yet.
create or replace function public.lottery_alerts_locked()
returns table(id uuid, email text, boroughs text[], kinds text[], token uuid, created_at timestamptz)
language sql
security definer
set search_path to 'public'
as $$
  select s.id, s.email, s.boroughs, s.kinds, s.token, s.created_at
    from lottery_alert_subs s
   where s.unsubscribed_at is null
     and s.grandfathered_at is null
     and s.locked_emailed_at is null
     and not exists (select 1 from auth.users u
                      where lower(u.email) = s.email and public.has_plus(u.id))
   order by s.created_at;
$$;
revoke all on function public.lottery_alerts_locked() from public, anon, authenticated;
grant execute on function public.lottery_alerts_locked() to service_role;

create or replace function public.lottery_alerts_mark_locked(p_ids uuid[])
returns void
language sql
security definer
set search_path to 'public'
as $$
  update public.lottery_alert_subs set locked_emailed_at = now() where id = any(p_ids);
$$;
revoke all on function public.lottery_alerts_mark_locked(uuid[]) from public, anon, authenticated;
grant execute on function public.lottery_alerts_mark_locked(uuid[]) to service_role;

notify pgrst, 'reload schema';

-- Dashboard: new (non-grandfathered) alert sign-ups in a range, and how many
-- of them are unlocked now (the account has Plus). Service role only.
create or replace function public.dashboard_alert_plus(p_since timestamptz)
returns jsonb
language sql
stable
security definer
set search_path to 'public'
as $$
  select jsonb_build_object(
    'signups', count(*),
    'unlocked', count(*) filter (where exists (select 1 from auth.users u
                                  where lower(u.email) = s.email and public.has_plus(u.id))),
    'emailed', count(*) filter (where s.locked_emailed_at is not null))
    from lottery_alert_subs s
   where s.grandfathered_at is null
     and (p_since is null or s.created_at >= p_since);
$$;
revoke all on function public.dashboard_alert_plus(timestamptz) from public, anon, authenticated;
grant execute on function public.dashboard_alert_plus(timestamptz) to service_role;

notify pgrst, 'reload schema';
