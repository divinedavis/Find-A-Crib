-- Building chat (owner, 2026-10-17: "create a chat button ... so people of
-- this building can chat with each other in real time, make it encrypted
-- e2e"; any signed-in account can join, and a member sees only messages sent
-- after they joined).
--
-- End to end: the server stores ciphertext it cannot read. Each phone keeps
-- a Curve25519 key in its Keychain and publishes the public half here
-- (chat_keys). A message is sealed with a fresh random key; that key is
-- wrapped once per member (ECDH sender x member, HKDF, ChaCha20-Poly1305)
-- and the wrapped copies ride in chat_messages.keys, one per member id. The
-- display name is inside the ciphertext too. What the server does see:
-- who is in which building's chat, who sent a message and when, and sizes.
--
-- Apple 1.2 (user-generated content): reports, blocks, a ban list, and terms
-- accepted before joining. A report carries the plaintext of the one message
-- the reporter chose to send us (they can read it; we can't otherwise);
-- error_report.py mails new reports to the owner within the hour.

create table if not exists public.chat_keys (
  user_id uuid primary key references auth.users(id) on delete cascade,
  public_key text not null check (length(public_key) between 40 and 64),  -- base64 of 32 bytes
  updated_at timestamptz not null default now()
);

create table if not exists public.chat_members (
  bbl text not null check (bbl ~ '^[0-9]{10}$'),
  user_id uuid not null references auth.users(id) on delete cascade,
  joined_at timestamptz not null default now(),
  agreed_terms_at timestamptz not null,
  primary key (bbl, user_id)
);
create index if not exists chat_members_user on public.chat_members(user_id);

create table if not exists public.chat_bans (
  user_id uuid primary key references auth.users(id) on delete cascade,
  reason text,
  created_at timestamptz not null default now()
);

create table if not exists public.chat_messages (
  id bigint generated always as identity primary key,
  bbl text not null check (bbl ~ '^[0-9]{10}$'),
  sender uuid not null default auth.uid() references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  salt text not null check (length(salt) between 16 and 64),
  ciphertext text not null check (length(ciphertext) between 1 and 12000),
  keys jsonb not null check (jsonb_typeof(keys) = 'object')
);
create index if not exists chat_messages_bbl_time on public.chat_messages(bbl, id desc);

create table if not exists public.chat_blocks (
  blocker uuid not null default auth.uid() references auth.users(id) on delete cascade,
  blocked uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (blocker, blocked)
);

create table if not exists public.chat_reports (
  id bigint generated always as identity primary key,
  message_id bigint references public.chat_messages(id) on delete set null,
  bbl text not null,
  reporter uuid not null default auth.uid() references auth.users(id) on delete cascade,
  sender uuid,
  plaintext text check (length(plaintext) <= 4000),
  reason text check (length(reason) <= 200),
  created_at timestamptz not null default now(),
  handled_at timestamptz
);

alter table public.chat_keys enable row level security;
alter table public.chat_members enable row level security;
alter table public.chat_bans enable row level security;
alter table public.chat_messages enable row level security;
alter table public.chat_blocks enable row level security;
alter table public.chat_reports enable row level security;

create or replace function public.chat_is_member(p_bbl text)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from chat_members where bbl = p_bbl and user_id = auth.uid())
$$;
create or replace function public.chat_is_banned()
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from chat_bans where user_id = auth.uid())
$$;
revoke all on function public.chat_is_member(text) from public, anon;
revoke all on function public.chat_is_banned() from public, anon;
grant execute on function public.chat_is_member(text) to authenticated;
grant execute on function public.chat_is_banned() to authenticated;

-- Keys: a member's phone needs every member's public key to wrap for them.
drop policy if exists chat_keys_read on public.chat_keys;
create policy chat_keys_read on public.chat_keys for select to authenticated using (true);
drop policy if exists chat_keys_own on public.chat_keys;
create policy chat_keys_own on public.chat_keys for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

-- Members: visible to the building's members; join and leave yourself.
drop policy if exists chat_members_read on public.chat_members;
create policy chat_members_read on public.chat_members for select to authenticated
  using (public.chat_is_member(bbl));
drop policy if exists chat_members_join on public.chat_members;
create policy chat_members_join on public.chat_members for insert to authenticated
  with check (user_id = auth.uid() and not public.chat_is_banned());
drop policy if exists chat_members_leave on public.chat_members;
create policy chat_members_leave on public.chat_members for delete to authenticated
  using (user_id = auth.uid());

-- Messages: a member reads the ones wrapped for them (so only what was sent
-- after they joined) and posts as themselves, unless banned. No updates;
-- a sender may delete their own.
drop policy if exists chat_messages_read on public.chat_messages;
create policy chat_messages_read on public.chat_messages for select to authenticated
  using (public.chat_is_member(bbl) and keys ? auth.uid()::text);
drop policy if exists chat_messages_post on public.chat_messages;
create policy chat_messages_post on public.chat_messages for insert to authenticated
  with check (sender = auth.uid() and public.chat_is_member(bbl) and not public.chat_is_banned());
drop policy if exists chat_messages_delete on public.chat_messages;
create policy chat_messages_delete on public.chat_messages for delete to authenticated
  using (sender = auth.uid());

drop policy if exists chat_blocks_own on public.chat_blocks;
create policy chat_blocks_own on public.chat_blocks for all to authenticated
  using (blocker = auth.uid()) with check (blocker = auth.uid());

-- Reports: write-only for the reporter; the owner reads them with the service key.
drop policy if exists chat_reports_file on public.chat_reports;
create policy chat_reports_file on public.chat_reports for insert to authenticated
  with check (reporter = auth.uid() and public.chat_is_member(bbl));

grant select, insert, update, delete on public.chat_keys to authenticated;
grant select, insert, delete on public.chat_members to authenticated;
grant select, insert, delete on public.chat_messages to authenticated;
grant select, insert, delete on public.chat_blocks to authenticated;
grant insert on public.chat_reports to authenticated;
revoke all on public.chat_keys, public.chat_members, public.chat_messages,
              public.chat_blocks, public.chat_reports, public.chat_bans from anon;

-- Flood guard: 30 messages a minute per sender.
create or replace function public.chat_rate_limit()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if (select count(*) from chat_messages where sender = new.sender
        and created_at > now() - interval '1 minute') >= 30 then
    raise exception 'slow down' using errcode = 'P0001';
  end if;
  return new;
end $$;
drop trigger if exists chat_rate_limit on public.chat_messages;
create trigger chat_rate_limit before insert on public.chat_messages
  for each row execute function public.chat_rate_limit();

-- Live delivery: Realtime applies the select policy above per subscriber.
do $$ begin
  alter publication supabase_realtime add table public.chat_messages;
exception when duplicate_object then null; end $$;
