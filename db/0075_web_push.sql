-- Notifications in a browser (owner, 2026-11-10: Web Push). A signed-in
-- visitor turns them on for a browser in the account panel; webpush.py sends
-- the lottery, re-rental and Your Casa alerts there as well as by email and
-- APNs. Kept apart from device_tokens so the APNs code never sees one.
--
-- endpoint is the browser's push-service address (fcm.googleapis.com,
-- *.push.apple.com, Mozilla, Windows; findacrib-api checks it); p256dh and
-- auth are the browser's keys the message is encrypted for. The account
-- comes from the verified session, never the client.
create table if not exists public.web_push_subs (
  endpoint   text primary key check (length(endpoint) <= 1000),
  user_id    uuid not null references auth.users (id) on delete cascade,
  p256dh     text not null check (length(p256dh) <= 120),
  auth       text not null check (length(auth) <= 120),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists web_push_subs_user_idx on public.web_push_subs (user_id);

alter table public.web_push_subs enable row level security;
revoke all on public.web_push_subs from public, anon, authenticated;
grant select, insert, update, delete on public.web_push_subs to service_role;

-- Files a browser against an account, keeping at most p_max per account (the
-- oldest goes). Returns true when the browser is new, so the API can send
-- one "Notifications are on" message.
create or replace function public.web_push_upsert(p_user_id uuid, p_endpoint text, p_p256dh text, p_auth text, p_max int default 20)
returns boolean language plpgsql security definer set search_path = public as $$
declare known boolean;
begin
  select exists(select 1 from public.web_push_subs where endpoint = p_endpoint) into known;
  insert into public.web_push_subs (endpoint, user_id, p256dh, auth)
  values (p_endpoint, p_user_id, p_p256dh, p_auth)
  on conflict (endpoint) do update
    set user_id = excluded.user_id, p256dh = excluded.p256dh, auth = excluded.auth, updated_at = now();
  delete from public.web_push_subs
   where user_id = p_user_id
     and endpoint in (select endpoint from public.web_push_subs where user_id = p_user_id
                       order by updated_at desc offset greatest(p_max, 1));
  return not known;
end $$;

-- Turning notifications off: only the caller's own browser.
create or replace function public.web_push_remove_own(p_endpoint text, p_user_id uuid)
returns void language sql security definer set search_path = public as $$
  delete from public.web_push_subs where endpoint = p_endpoint and user_id = p_user_id;
$$;

-- The push service said the browser is gone (404/410).
create or replace function public.web_push_remove(p_endpoint text)
returns void language sql security definer set search_path = public as $$
  delete from public.web_push_subs where endpoint = p_endpoint;
$$;

create or replace function public.web_push_count(p_user_id uuid)
returns integer language sql security definer set search_path = public as $$
  select count(*)::int from public.web_push_subs where user_id = p_user_id;
$$;

-- The alert jobs' one lookup per run, as device_tokens_for_emails.
create or replace function public.web_push_for_emails(p_emails text[])
returns table (email text, endpoint text, p256dh text, auth text)
language sql security definer set search_path = public as $$
  select lower(u.email), w.endpoint, w.p256dh, w.auth
    from public.web_push_subs w
    join auth.users u on u.id = w.user_id
   where lower(u.email) = any(select lower(e) from unnest(coalesce(p_emails, '{}')) e);
$$;

revoke all on function public.web_push_upsert(uuid, text, text, text, int) from public, anon, authenticated;
revoke all on function public.web_push_remove_own(text, uuid) from public, anon, authenticated;
revoke all on function public.web_push_remove(text) from public, anon, authenticated;
revoke all on function public.web_push_count(uuid) from public, anon, authenticated;
revoke all on function public.web_push_for_emails(text[]) from public, anon, authenticated;
grant execute on function public.web_push_upsert(uuid, text, text, text, int) to service_role;
grant execute on function public.web_push_remove_own(text, uuid) to service_role;
grant execute on function public.web_push_remove(text) to service_role;
grant execute on function public.web_push_count(uuid) to service_role;
grant execute on function public.web_push_for_emails(text[]) to service_role;

notify pgrst, 'reload schema';
