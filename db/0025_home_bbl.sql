-- 0025: "My apartment" — the building a user pinned as their own, kept on
-- auth.users.raw_user_meta_data->>'home_bbl' by the site (same place as the
-- theme; no table, no RLS policy, works for free accounts). The saved-building
-- dispatcher reads it so the email can say "your building" instead of
-- "a building you saved".
drop function if exists public.saved_watchers();
create function public.saved_watchers()
returns table (
  user_id       uuid,
  email         text,
  token         uuid,
  created_at    timestamptz,
  alerts_off    boolean,
  digest_off    boolean,
  lifecycle_off boolean,
  sent_steps    jsonb,
  last_seen     timestamptz,
  bbls          text[],
  viewed_boros  text[],
  home_bbl      text
)
language sql security definer set search_path = public, auth as $$
  select u.id,
         u.email::text,
         p.token,
         u.created_at,
         p.unsubscribed_at is not null,
         p.digest_unsubscribed_at is not null,
         p.lifecycle_unsubscribed_at is not null,
         coalesce(p.sent_steps, '[]'::jsonb),
         v.last_seen,
         coalesce(s.bbls, '{}'::text[]),
         coalesce(e.boros, '{}'::text[]),
         case when (u.raw_user_meta_data->>'home_bbl') ~ '^\d{10}$'
              then u.raw_user_meta_data->>'home_bbl' end
    from auth.users u
    join alert_prefs p on p.user_id = u.id
    left join (select user_id, array_agg(bbl order by created_at desc) bbls
                 from saved_buildings group by 1) s on s.user_id = u.id
    left join (select user_id, max(created_at) last_seen
                 from visits where user_id is not null group by 1) v on v.user_id = u.id
    left join (select user_id, array_agg(boro order by last desc) boros
                 from (select user_id, props->>'boro' boro, max(created_at) last
                         from events
                        where user_id is not null
                          and event = 'building_view'
                          and props->>'boro' in ('M', 'Bk', 'Q', 'Bx', 'SI')
                          and created_at > now() - interval '90 days'
                        group by 1, 2) x
                group by 1) e on e.user_id = u.id
   where u.email is not null
     and u.email not like '%@example.com';
$$;
revoke all on function public.saved_watchers() from public, anon, authenticated;
grant execute on function public.saved_watchers() to service_role;
