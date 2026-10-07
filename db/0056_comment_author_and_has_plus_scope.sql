-- 0056: comment author integrity + has_plus() scoped to the caller
-- (security audit 2026-10-07, L2).
--
-- 1. building_comments.author was whatever the client sent, so a signed-in
--    user could post as "Find A Crib" or as another commenter. A BEFORE
--    INSERT trigger now sets it server-side, from the same fields the web and
--    iOS clients already use (user_metadata full_name/name, else the email's
--    local part, else 'Member', 60 chars). The INSERT grant on the column
--    stays: released App Store builds send `author`, and revoking it would
--    turn every comment post from those builds into a 42501. Whatever they
--    send is simply overwritten.
--
-- 2. has_plus(uid) was SECURITY DEFINER and answered for ANY uid, so any
--    account could ask whether any commenter (user_id is public on comments)
--    pays. The logic moves to private.has_plus_raw(); public.has_plus() is now
--    SECURITY INVOKER and answers false when an anon/authenticated caller asks
--    about someone else. Definer functions owned by postgres
--    (grant_referral_plus, plus_emails, dashboard_alert_*) and service_role
--    (api_server.py's ai_gateway, founding_members.py) are unaffected.
--
-- NOT done: hiding building_comments.user_id from anon. Both clients —
-- including the App Store iOS build, which is frozen — select user_id while
-- signed out (delete button, likes, blocks), and a column revoke would fail
-- the whole query and blank every comment thread. It is a random UUID, and
-- with (2) it no longer joins to anything a caller can look up.

create schema if not exists private;
revoke all on schema private from public, anon;
grant usage on schema private to authenticated, service_role;

create or replace function private.has_plus_raw(uid uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.subscriptions s
    where s.user_id = uid
      and s.status in ('active','trialing')
      and (s.current_period_end is null or s.current_period_end > now())
  );
$$;
revoke all on function private.has_plus_raw(uuid) from public, anon;
grant execute on function private.has_plus_raw(uuid) to authenticated, service_role;

create or replace function public.has_plus(uid uuid)
returns boolean
language sql
stable
security invoker
set search_path = public
as $$
  select case
    when current_user in ('anon', 'authenticated') and uid is distinct from auth.uid() then false
    else private.has_plus_raw(uid)
  end;
$$;
revoke all on function public.has_plus(uuid) from public, anon;
grant execute on function public.has_plus(uuid) to authenticated, service_role;

create or replace function public.set_comment_author()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  md    jsonb;
  email text;
  n     text;
begin
  select u.raw_user_meta_data, u.email into md, email from auth.users u where u.id = new.user_id;
  n := btrim(coalesce(nullif(btrim(md->>'full_name'), ''), md->>'name', ''));
  if n = '' then
    n := coalesce(nullif(split_part(coalesce(email, ''), '@', 1), ''), 'Member');
  end if;
  new.author := left(n, 60);
  return new;
end;
$$;
revoke all on function public.set_comment_author() from public, anon, authenticated;

drop trigger if exists building_comments_author on public.building_comments;
create trigger building_comments_author
  before insert or update of author, user_id on public.building_comments
  for each row execute function public.set_comment_author();

notify pgrst, 'reload schema';
