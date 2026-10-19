-- Building chat: "Couldn't join the chat" on build 144 (owner, 2026-10-18,
-- 251 Dekalb). The app joins with an upsert that returns the new row, and a
-- returned row must pass the SELECT policy. chat_members_read only admitted
-- rows of buildings you are already a member of, and chat_is_member() can't
-- see the row the same statement is inserting, so every first join failed
-- with "new row violates row-level security policy" (403). The 11/11 RLS
-- check of 10/18 inserted without RETURNING, so it never hit this.
--
-- Your own membership rows are always yours to read; everything else is
-- unchanged (other members' rows still need you to be a member).
drop policy if exists chat_members_read on public.chat_members;
create policy chat_members_read on public.chat_members for select to authenticated
  using (user_id = auth.uid() or public.chat_is_member(bbl));
