-- Let a folder owner revoke a shared link (security review 2026-07-17).
-- Shared folder links were permanent with no way to revoke; rotating the
-- share_token invalidates every previously-shared URL for that folder.
-- Owner-only (checked via auth.uid()), returns the new token.

create or replace function public.reset_share_token(p_category_id uuid)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  new_token uuid;
begin
  update categories
     set share_token = gen_random_uuid()
   where id = p_category_id and user_id = auth.uid()
  returning share_token into new_token;
  if new_token is null then
    raise exception 'not your folder';
  end if;
  return new_token;
end;
$$;
revoke all on function public.reset_share_token(uuid) from public;
grant execute on function public.reset_share_token(uuid) to authenticated;
