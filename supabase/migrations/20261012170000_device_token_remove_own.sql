-- Sign-out now unregisters the phone (owner, 2026-10-12: an alert pushed to a
-- phone that had signed out). /push/unregister passes the caller's id, so a
-- signed-in user can remove only their OWN device rows — the old
-- device_token_remove(token) deleted anyone's row by token.
create or replace function public.device_token_remove_own(p_token text, p_user_id uuid)
returns void
language sql
security definer
set search_path = public
as $$
  delete from public.device_tokens where token = p_token and user_id = p_user_id;
$$;
revoke all on function public.device_token_remove_own(text, uuid) from public, anon, authenticated;
grant execute on function public.device_token_remove_own(text, uuid) to service_role;
