-- Push notifications for borough alerts (owner, 2026-09-17: "the alerts
-- should be sent via the app notifications"). The iPhone app registers its
-- APNs token against the signed-in account; the alert dispatcher looks up
-- the tokens behind the addresses it is about to email and pushes the same
-- alert to the phone.
--
-- `env` is the device's CLAIM about which APNs host it registered with
-- (TestFlight and the App Store are production; only an Xcode-run build is
-- sandbox). It can be wrong, so the sender retries the other host on
-- BadDeviceToken and refiles the row through device_token_refile; only
-- 410 Unregistered removes a token.

create table if not exists public.device_tokens (
  token      text primary key,
  user_id    uuid not null references auth.users(id) on delete cascade,
  env        text not null default 'production' check (env in ('production', 'sandbox')),
  platform   text not null default 'ios',
  build      text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists device_tokens_user_idx on public.device_tokens (user_id);

alter table public.device_tokens enable row level security;
revoke all on public.device_tokens from public, anon, authenticated;
grant select, insert, update, delete on public.device_tokens to service_role;

-- Written by findacrib-api's /api/push/register, which has verified the
-- session and passes the account id — the token itself never comes from a
-- client claim about WHOSE it is.
create or replace function public.device_token_upsert(p_user_id uuid, p_token text, p_env text, p_build text)
returns void language sql security definer set search_path = public as $$
  insert into public.device_tokens (token, user_id, env, build, updated_at)
  values (p_token, p_user_id, coalesce(nullif(p_env, ''), 'production'), p_build, now())
  on conflict (token) do update
    set user_id = excluded.user_id, env = excluded.env, build = excluded.build, updated_at = now();
$$;

create or replace function public.device_token_remove(p_token text)
returns void language sql security definer set search_path = public as $$
  delete from public.device_tokens where token = p_token;
$$;

create or replace function public.device_token_refile(p_token text, p_env text)
returns void language sql security definer set search_path = public as $$
  update public.device_tokens set env = p_env, updated_at = now()
   where token = p_token and p_env in ('production', 'sandbox');
$$;

-- The dispatcher's one lookup per run: every device behind the addresses it
-- is about to alert. Email is matched case-insensitively against auth.users,
-- which is where the alert subscription's address came from in the first
-- place (alerts need an account since 2026-09-08).
create or replace function public.device_tokens_for_emails(p_emails text[])
returns table (email text, token text, env text)
language sql security definer set search_path = public as $$
  select lower(u.email), d.token, d.env
    from public.device_tokens d
    join auth.users u on u.id = d.user_id
   where lower(u.email) = any(select lower(e) from unnest(coalesce(p_emails, '{}')) e);
$$;

revoke all on function public.device_token_upsert(uuid, text, text, text) from public, anon, authenticated;
revoke all on function public.device_token_remove(text) from public, anon, authenticated;
revoke all on function public.device_token_refile(text, text) from public, anon, authenticated;
revoke all on function public.device_tokens_for_emails(text[]) from public, anon, authenticated;
grant execute on function public.device_token_upsert(uuid, text, text, text) to service_role;
grant execute on function public.device_token_remove(text) to service_role;
grant execute on function public.device_token_refile(text, text) to service_role;
grant execute on function public.device_tokens_for_emails(text[]) to service_role;
