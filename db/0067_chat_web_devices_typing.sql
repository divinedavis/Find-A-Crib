-- Building chat on findacrib.com, plus typing bubbles (owner, 2026-10-19:
-- "allow live message bubbling for when people are typing" ... "build chat
-- on the web too").
--
-- Devices. 0063 gave each account ONE key (chat_keys), made by the iPhone and
-- kept in its Keychain. A browser can't use that key, and publishing its own
-- into chat_keys would lock the phone out. So a browser registers a device:
-- its own X25519 key in chat_devices, under a random device id. A sender now
-- wraps the message key once per phone key (keys["<uid>"], as before) AND
-- once per browser (keys["<uid>:<device>"]). A message sent from a browser
-- names its device in sender_device so readers know which public key sealed
-- it; null means the account's phone key, which keeps old messages and old
-- app builds working unchanged.
--
-- Typing. Broadcasts on the private Realtime topic chat-typing:<bbl>; only
-- that building's members may join, send or receive. The payload is the
-- sender's account id and nothing else (names stay inside the ciphertext).

create table if not exists public.chat_devices (
  user_id uuid not null references auth.users(id) on delete cascade,
  device_id text not null check (device_id ~ '^[a-f0-9]{16,32}$'),
  public_key text not null check (length(public_key) between 40 and 64),  -- base64 of 32 bytes
  platform text not null default 'web' check (platform in ('web')),
  updated_at timestamptz not null default now(),
  primary key (user_id, device_id)
);
alter table public.chat_devices enable row level security;

-- Same rules as chat_keys: public halves are readable by any signed-in
-- member's client (it needs them to wrap); you manage only your own.
drop policy if exists chat_devices_read on public.chat_devices;
create policy chat_devices_read on public.chat_devices for select to authenticated using (true);
drop policy if exists chat_devices_own on public.chat_devices;
create policy chat_devices_own on public.chat_devices for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
grant select, insert, update, delete on public.chat_devices to authenticated;
revoke all on public.chat_devices from anon;

-- A browser may keep at most 10 devices per account (cleared site data makes
-- a new one each time).
create or replace function public.chat_devices_cap()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if (select count(*) from chat_devices where user_id = new.user_id) >= 10 then
    delete from chat_devices where (user_id, device_id) in (
      select user_id, device_id from chat_devices where user_id = new.user_id
      order by updated_at asc limit 1);
  end if;
  return new;
end $$;
revoke execute on function public.chat_devices_cap() from public, anon, authenticated;
drop trigger if exists chat_devices_cap on public.chat_devices;
create trigger chat_devices_cap before insert on public.chat_devices
  for each row execute function public.chat_devices_cap();

alter table public.chat_messages add column if not exists sender_device text
  check (sender_device is null or sender_device ~ '^[a-f0-9]{16,32}$');

-- Read: a member sees a message wrapped for their phone OR any of their
-- browsers.
drop policy if exists chat_messages_read on public.chat_messages;
create policy chat_messages_read on public.chat_messages for select to authenticated
  using (public.chat_is_member(bbl) and (
    keys ? auth.uid()::text
    or exists (select 1 from jsonb_object_keys(keys) k where starts_with(k, auth.uid()::text || ':'))));

-- Typing bubbles: private broadcast topic per building, members only.
drop policy if exists chat_typing_receive on realtime.messages;
create policy chat_typing_receive on realtime.messages for select to authenticated
  using (realtime.messages.extension = 'broadcast'
         and split_part(realtime.topic(), ':', 1) = 'chat-typing'
         and public.chat_is_member(split_part(realtime.topic(), ':', 2)));
drop policy if exists chat_typing_send on realtime.messages;
create policy chat_typing_send on realtime.messages for insert to authenticated
  with check (realtime.messages.extension = 'broadcast'
              and split_part(realtime.topic(), ':', 1) = 'chat-typing'
              and public.chat_is_member(split_part(realtime.topic(), ':', 2)));
