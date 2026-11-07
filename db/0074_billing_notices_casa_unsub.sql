-- Legal fixes, 2026-11-07 (owner: "fix this").
--
-- 1. billing_notices — the trial-ending reminder California's auto-renewal
--    law (Bus. & Prof. Code 17602) and the FTC's ROSCA expect before a free
--    trial turns into a paid charge. Stripe sends customer.subscription.
--    trial_will_end three days before the trial ends; the stripe-webhook edge
--    function records it here (one row per subscription + trial end), and
--    billing_notices.py on the droplet (every 10 min, deploy/cron-rentmap-
--    billing) mails it through growth/emailkit and stamps sent_at. It is a
--    REQUIRED notice: it never claims the one-email-a-day slot (mailcap) and
--    never waits behind it. Service role only — it holds addresses.
create table if not exists public.billing_notices (
  id                     bigint generated always as identity primary key,
  kind                   text not null default 'trial_will_end' check (kind in ('trial_will_end')),
  stripe_event_id        text not null unique,
  stripe_subscription_id text not null,
  stripe_customer_id     text,
  user_id                uuid references auth.users (id) on delete cascade,
  email                  text not null,
  amount_cents           integer not null,
  currency               text not null default 'usd',
  interval               text not null default 'month',
  trial_end              timestamptz not null,
  created_at             timestamptz not null default now(),
  sent_at                timestamptz,
  attempts               integer not null default 0,
  last_error             text,
  -- Stripe may resend the event (retries, a re-subscribed endpoint): one
  -- reminder per subscription per trial end, whatever the event id.
  unique (stripe_subscription_id, trial_end, kind)
);
alter table public.billing_notices enable row level security;
-- From 2026-10-30 new public tables get no default grants: say it outright.
revoke all on public.billing_notices from public, anon, authenticated;
grant select, insert, update, delete on public.billing_notices to service_role;
grant usage, select on sequence public.billing_notices_id_seq to service_role;

-- 2. One-click unsubscribe for Your Crib (casa) alerts. The email now carries
--    the account's alert_prefs token (the same one the saved-building alerts
--    use) and api_server.py /email/unsubscribe?k=casa calls this with the
--    service role. Stopping = deleting the watch, which is exactly what the
--    "Stop" button in Your Crib does.
create or replace function public.unsubscribe_casa(p_token uuid)
returns boolean language sql security definer set search_path = public as $$
  with gone as (
    delete from casa_watches w
     using alert_prefs p
     where p.token = p_token and w.user_id = p.user_id
    returning 1
  )
  select exists (select 1 from gone);
$$;
revoke execute on function public.unsubscribe_casa(uuid) from public, anon, authenticated;
grant execute on function public.unsubscribe_casa(uuid) to service_role;

notify pgrst, 'reload schema';
