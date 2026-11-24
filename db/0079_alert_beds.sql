-- 2026-11-24: the owner picked "1" under Beds in the app's Lotteries filter
-- and was still alerted about a studio. That choice only filtered the list on
-- the phone; the alerts never heard about it. A subscriber's bedroom sizes now
-- live on the subscription, and the sender skips a listing that states its
-- sizes when none of them is one the subscriber asked for.
--
-- beds: 0 = studio … 4 = four or more (the same buckets as the app's Beds
-- row). null = any size, which is what everyone has until they choose.
alter table public.lottery_alert_subs add column if not exists beds smallint[]
  check (beds is null or (beds <@ array[0, 1, 2, 3, 4]::smallint[] and cardinality(beds) between 1 and 5));

create or replace function public.lottery_alerts_set_beds(p_email text, p_beds integer[])
returns void language sql security definer set search_path to 'public' as $$
  update lottery_alert_subs
     set beds = (select array_agg(distinct b::smallint order by b::smallint)
                   from unnest(coalesce(p_beds, '{}'::integer[])) as b where b between 0 and 4),
         updated_at = now()
   where email = lower(trim(p_email)) and unsubscribed_at is null;
$$;

create or replace function public.lottery_alerts_beds_all()
returns table(email text, beds smallint[]) language sql stable security definer set search_path to 'public' as $$
  select email, beds from lottery_alert_subs where unsubscribed_at is null and beds is not null;
$$;

create or replace function public.lottery_alerts_beds(p_email text)
returns smallint[] language sql stable security definer set search_path to 'public' as $$
  select beds from lottery_alert_subs where email = lower(trim(p_email)) and unsubscribed_at is null limit 1;
$$;

-- service_role only, like every other alerts function: these read and write
-- by email address and must never be callable from a browser.
revoke all on function public.lottery_alerts_set_beds(text, integer[]) from public, anon, authenticated;
revoke all on function public.lottery_alerts_beds_all() from public, anon, authenticated;
revoke all on function public.lottery_alerts_beds(text) from public, anon, authenticated;
grant execute on function public.lottery_alerts_set_beds(text, integer[]) to service_role;
grant execute on function public.lottery_alerts_beds_all() to service_role;
grant execute on function public.lottery_alerts_beds(text) to service_role;
notify pgrst, 'reload schema';
