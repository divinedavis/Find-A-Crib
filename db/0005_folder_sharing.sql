-- Folder (category) sharing. Every folder gets an unguessable share token;
-- anyone with the link can view the folder name + its saved buildings via
-- get_shared_folder(). Possession of the uuid is the authorization (same
-- pattern as unsubscribe_alerts). Rename/delete stay owner-only via the
-- existing cat_update_own / cat_delete_own policies.

alter table public.categories
  add column if not exists share_token uuid not null unique default gen_random_uuid();

create or replace function public.get_shared_folder(p_token uuid)
returns jsonb language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'name', c.name,
    'bbls', coalesce((select jsonb_agg(sb.bbl)
                      from saved_buildings sb
                      where sb.category_id = c.id), '[]'::jsonb))
  from categories c
  where c.share_token = p_token;
$$;
revoke all on function public.get_shared_folder(uuid) from public;
grant execute on function public.get_shared_folder(uuid) to anon, authenticated;
