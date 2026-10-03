-- 2026-10-03 (owner's AI/ML list item 6, "lets be smarter about alerts"):
-- a subscriber's household size, so a re-rental's income limits (now read off
-- its flyer, featured_units.json) can be checked against the right row.
alter table public.lottery_alert_subs add column if not exists household_size smallint
  check (household_size between 1 and 12);

create or replace function public.lottery_alerts_set_household(p_email text, p_household integer)
returns void language sql security definer set search_path to 'public' as $$
  update lottery_alert_subs set household_size = p_household, updated_at = now()
   where email = lower(trim(p_email)) and unsubscribed_at is null;
$$;

create or replace function public.lottery_alerts_households()
returns table(email text, household_size smallint) language sql stable security definer set search_path to 'public' as $$
  select email, household_size from lottery_alert_subs where unsubscribed_at is null and household_size is not null;
$$;

create or replace function public.lottery_alerts_household(p_email text)
returns smallint language sql stable security definer set search_path to 'public' as $$
  select household_size from lottery_alert_subs where email = lower(trim(p_email)) and unsubscribed_at is null limit 1;
$$;

revoke all on function public.lottery_alerts_set_household(text, integer) from public, anon, authenticated;
revoke all on function public.lottery_alerts_households() from public, anon, authenticated;
revoke all on function public.lottery_alerts_household(text) from public, anon, authenticated;
grant execute on function public.lottery_alerts_set_household(text, integer) to service_role;
grant execute on function public.lottery_alerts_households() to service_role;
grant execute on function public.lottery_alerts_household(text) to service_role;
notify pgrst, 'reload schema';
