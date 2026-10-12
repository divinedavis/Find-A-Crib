-- Paying customers by the dashboard's range (owner, 2026-10-12: "show a tile
-- that captures our paying customers for the filter date that's selected").
-- subscriptions had no start date, so a range could only be a cohort of
-- accounts. started_at is when the subscription began: set here on the first
-- insert/update that makes a row Plus, whichever path wrote it (Stripe
-- webhook, apple-subscription, apple-notifications, a hand backfill), so no
-- function has to remember to send it. Existing rows were backfilled from
-- Stripe (subscription.start_date) and the App Store Server API (first
-- purchaseDate in the transaction history).
alter table public.subscriptions add column if not exists started_at timestamptz;

create or replace function private.subscriptions_set_started_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.started_at is null and new.plan = 'plus' and new.status in ('active', 'trialing') then
    new.started_at := now();
  end if;
  return new;
end $$;

drop trigger if exists subscriptions_started_at on public.subscriptions;
create trigger subscriptions_started_at
  before insert or update on public.subscriptions
  for each row execute function private.subscriptions_set_started_at();

-- Who paid at any point in [since, now]: a live paying subscription, or one
-- that ended inside the range (Stripe rows carry no period end, so a
-- cancelled one ends at its last update). Trials have not paid and are
-- counted on their own; comped/founding/referral and the owner's accounts are
-- left out, as everywhere on the dashboard. since = null is all time.
create or replace function public.dashboard_paying(since timestamptz default null)
returns jsonb
language sql stable security definer
set search_path = public
as $$
  with s as (
    select x.*, coalesce(x.current_period_end, case when x.status not in ('active', 'trialing') then x.updated_at end) as ends
      from public.subscriptions x
     where x.plan = 'plus'
       and (x.stripe_subscription_id is not null or x.provider = 'apple')
       and x.user_id not in (select public.dashboard_excluded_ids())
       and x.started_at is not null
  ), live as (
    select * from s where status in ('active', 'trialing') and (ends is null or ends > now())
  ), paid as (
    select * from live where status = 'active'
    union all
    select * from s where status not in ('active', 'trialing') and (since is null or ends >= since)
  )
  select jsonb_build_object(
    'paying', (select count(*) from paid),
    'new', (select count(*) from paid where since is null or started_at >= since),
    'ended', (select count(*) from paid where status not in ('active', 'trialing')),
    'trialing', (select count(*) from live where status = 'trialing'),
    'web', (select count(*) from paid where provider = 'stripe'),
    'app', (select count(*) from paid where provider = 'apple'),
    'paying_now', (select count(*) from live where status = 'active'));
$$;
revoke all on function public.dashboard_paying(timestamptz) from public, anon, authenticated;
grant execute on function public.dashboard_paying(timestamptz) to service_role;
