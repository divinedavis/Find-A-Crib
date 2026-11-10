-- Passkeys on findacrib.com (owner, 2026-11-10). passkeys.py checks every
-- ceremony; findacrib-api reaches these through the service role only, and
-- takes the account from the verified Supabase session (never the client).
-- The private key never leaves the visitor's device: only its public key,
-- a counter and when it was added and last used are kept.
create table if not exists public.passkeys (
  id           text primary key check (length(id) <= 1400),
  user_id      uuid not null references auth.users (id) on delete cascade,
  public_key   text not null check (length(public_key) <= 2000),
  alg          integer not null check (alg in (-7, -8, -257)),
  counter      bigint not null default 0,
  transports   text[] not null default '{}',
  name         text check (length(name) <= 60),
  created_at   timestamptz not null default now(),
  last_used_at timestamptz
);
create index if not exists passkeys_user_idx on public.passkeys (user_id);

-- One-use challenges, kept as a SHA-256 of the challenge.
create table if not exists public.passkey_challenges (
  hash       text primary key check (length(hash) = 64),
  purpose    text not null check (purpose in ('register', 'login')),
  user_id    uuid references auth.users (id) on delete cascade,
  expires_at timestamptz not null
);

alter table public.passkeys enable row level security;
alter table public.passkey_challenges enable row level security;
revoke all on public.passkeys, public.passkey_challenges from public, anon, authenticated;
grant select, insert, update, delete on public.passkeys, public.passkey_challenges to service_role;

create or replace function public.passkey_challenge_new(p_hash text, p_purpose text, p_user_id uuid, p_ttl integer default 300)
returns void language sql security definer set search_path = public as $$
  delete from public.passkey_challenges where expires_at < now();
  insert into public.passkey_challenges (hash, purpose, user_id, expires_at)
  values (p_hash, p_purpose, p_user_id, now() + make_interval(secs => least(greatest(p_ttl, 30), 600)));
$$;

-- Used once: the row goes as it is read.
create or replace function public.passkey_challenge_spend(p_hash text)
returns table (purpose text, user_id uuid, expires_epoch double precision)
language sql security definer set search_path = public as $$
  delete from public.passkey_challenges c where c.hash = p_hash
  returning c.purpose, c.user_id, extract(epoch from c.expires_at)::double precision;
$$;

-- 'ok', 'exists' (that passkey is already kept) or 'limit' (p_max reached).
create or replace function public.passkey_add(p_id text, p_user_id uuid, p_public_key text, p_alg integer, p_counter bigint,
                                              p_transports text[], p_name text, p_max integer default 10)
returns text language plpgsql security definer set search_path = public as $$
begin
  if exists (select 1 from public.passkeys where id = p_id) then return 'exists'; end if;
  if (select count(*) from public.passkeys where user_id = p_user_id) >= p_max then return 'limit'; end if;
  insert into public.passkeys (id, user_id, public_key, alg, counter, transports, name)
  values (p_id, p_user_id, p_public_key, p_alg, coalesce(p_counter, 0), coalesce(p_transports, '{}'), p_name);
  return 'ok';
end $$;

create or replace function public.passkey_get(p_id text)
returns table (id text, user_id uuid, public_key text, alg integer, counter bigint)
language sql security definer set search_path = public as $$
  select p.id, p.user_id, p.public_key, p.alg, p.counter from public.passkeys p where p.id = p_id;
$$;

create or replace function public.passkey_used(p_id text, p_counter bigint)
returns void language sql security definer set search_path = public as $$
  update public.passkeys set counter = greatest(counter, coalesce(p_counter, 0)), last_used_at = now() where id = p_id;
$$;

create or replace function public.passkey_list(p_user_id uuid)
returns table (id text, name text, created_at timestamptz, last_used_at timestamptz)
language sql security definer set search_path = public as $$
  select p.id, p.name, p.created_at, p.last_used_at from public.passkeys p where p.user_id = p_user_id order by p.created_at;
$$;

-- Only the caller's own passkey; returns how many went (0 or 1).
create or replace function public.passkey_remove(p_id text, p_user_id uuid)
returns integer language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  delete from public.passkeys where id = p_id and user_id = p_user_id;
  get diagnostics n = row_count;
  return n;
end $$;

do $$ declare f text; begin
  foreach f in array array[
    'passkey_challenge_new(text, text, uuid, integer)', 'passkey_challenge_spend(text)',
    'passkey_add(text, uuid, text, integer, bigint, text[], text, integer)', 'passkey_get(text)',
    'passkey_used(text, bigint)', 'passkey_list(uuid)', 'passkey_remove(text, uuid)']
  loop
    execute format('revoke all on function public.%s from public, anon, authenticated', f);
    execute format('grant execute on function public.%s to service_role', f);
  end loop;
end $$;

notify pgrst, 'reload schema';
