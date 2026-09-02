-- In-app account deletion for the iOS app (App Store Guideline 5.1.1(v): any
-- app that creates accounts must let the user delete theirs from inside it).
-- Same shape as WorkComp+/Spendcap: one SECURITY DEFINER function, owned by
-- postgres (which may DELETE from auth.users); every user-owned public table
-- here already references auth.users(id) on delete cascade, and this project
-- has no storage buckets, so nothing needs removing first.
create or replace function public.delete_account()
returns void language plpgsql security definer set search_path = public as $$
declare uid uuid := auth.uid();
begin
  if uid is null then raise exception 'Not authenticated'; end if;
  delete from auth.users where id = uid;
end; $$;
-- Supabase grants EXECUTE on new public functions to anon AND authenticated by
-- name; revoking from public alone leaves anon callable. Name the roles.
revoke all on function public.delete_account() from public, anon;
grant execute on function public.delete_account() to authenticated;
notify pgrst, 'reload schema';
