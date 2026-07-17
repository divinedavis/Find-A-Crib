-- Developer API: API keys, per-day usage metering, and an atomic
-- authorize-and-count function. All service-role only (the API service holds
-- the service_role key); never exposed to anon/authenticated.

create table if not exists public.api_keys (
  id            uuid primary key default gen_random_uuid(),
  key_hash      text not null unique,          -- sha256(plaintext key); plaintext shown once at creation
  key_prefix    text not null,                 -- first chars, for display (e.g. fac_live_ab12…)
  owner_email   text not null,
  tier          text not null default 'free' check (tier in ('free', 'pro', 'business')),
  status        text not null default 'active' check (status in ('active', 'revoked')),
  stripe_customer_id     text,
  stripe_subscription_id text,
  label         text,
  created_at    timestamptz not null default now()
);
alter table public.api_keys enable row level security;   -- no anon/authenticated policies → service_role only
revoke all on public.api_keys from anon, authenticated;

create table if not exists public.api_usage (
  key_id  uuid not null references public.api_keys(id) on delete cascade,
  day     date not null,
  count   int  not null default 0,
  primary key (key_id, day)
);
alter table public.api_usage enable row level security;
revoke all on public.api_usage from anon, authenticated;

-- Daily request limits per tier.
create or replace function public.api_tier_limit(p_tier text)
returns int language sql immutable as $$
  select case p_tier when 'business' then 500000 when 'pro' then 50000 else 1000 end;
$$;

-- Authorize a request by key hash and count it, atomically. Returns a json
-- verdict the API service turns into 200 / 401 / 429.
create or replace function public.api_authorize(p_key_hash text)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  k record;
  lim int;
  used int;
begin
  select * into k from api_keys where key_hash = p_key_hash and status = 'active';
  if not found then
    return jsonb_build_object('allowed', false, 'reason', 'invalid_key');
  end if;
  lim := api_tier_limit(k.tier);
  insert into api_usage (key_id, day, count) values (k.id, current_date, 1)
    on conflict (key_id, day) do update set count = api_usage.count + 1
    returning count into used;
  if used > lim then
    return jsonb_build_object('allowed', false, 'reason', 'rate_limited',
                              'tier', k.tier, 'limit', lim);
  end if;
  return jsonb_build_object('allowed', true, 'tier', k.tier, 'owner', k.owner_email,
                            'used', used, 'limit', lim, 'remaining', lim - used);
end;
$$;
revoke all on function public.api_authorize(text) from public, anon, authenticated;
grant execute on function public.api_authorize(text) to service_role;
