-- 2026-10-03 (owner): AI features, behind Find A Crib Plus, with a hard
-- $20/month ceiling across every model call. One row per call: who, which
-- feature, which model, tokens, and the cost in micro-dollars computed by
-- the API from the published per-token prices. The API refuses a call when
-- the month's total would pass the cap, and per user per feature per day.

create table if not exists public.ai_usage (
  id bigserial primary key,
  created_at timestamptz not null default now(),
  user_id uuid,
  feature text not null,
  model text not null,
  input_tokens integer not null default 0,
  output_tokens integer not null default 0,
  cost_micros bigint not null default 0,
  cached boolean not null default false,
  ok boolean not null default true
);
create index if not exists ai_usage_month on public.ai_usage (created_at);
create index if not exists ai_usage_user_day on public.ai_usage (user_id, feature, created_at);
alter table public.ai_usage enable row level security;   -- no policies: service role only

-- Micro-dollars spent this calendar month (New York time), all features.
create or replace function public.ai_spend_month()
returns bigint language sql stable security definer set search_path to 'public' as $$
  select coalesce(sum(cost_micros), 0)::bigint from ai_usage
   where created_at >= date_trunc('month', now() at time zone 'America/New_York') at time zone 'America/New_York';
$$;

-- Calls a user made to one feature since midnight New York time.
create or replace function public.ai_user_calls_today(p_user uuid, p_feature text)
returns integer language sql stable security definer set search_path to 'public' as $$
  select count(*)::int from ai_usage
   where user_id = p_user and feature = p_feature and not cached
     and created_at >= date_trunc('day', now() at time zone 'America/New_York') at time zone 'America/New_York';
$$;

revoke all on function public.ai_spend_month() from public, anon, authenticated;
revoke all on function public.ai_user_calls_today(uuid, text) from public, anon, authenticated;
grant execute on function public.ai_spend_month() to service_role;
grant execute on function public.ai_user_calls_today(uuid, text) to service_role;
revoke all on table public.ai_usage from anon, authenticated;
notify pgrst, 'reload schema';
