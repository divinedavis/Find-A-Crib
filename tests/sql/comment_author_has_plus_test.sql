-- Rollback-only check of db/0056 against the live database.
do $$
declare
  p uuid; o uuid := gen_random_uuid(); out text := ''; a text; b boolean;
begin
  select s.user_id into p from public.subscriptions s
   where s.status = 'active' and (s.current_period_end is null or s.current_period_end > now()) limit 1;
  insert into auth.users (id, instance_id, aud, role, email, raw_user_meta_data, created_at, updated_at)
  values (o, '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated',
          'zed.tester@example.invalid', '{}'::jsonb, now(), now());
  out := out || 'nested_postgres=' || public.has_plus(p) || ' ';
  perform set_config('request.jwt.claims', json_build_object('sub', o, 'role', 'authenticated')::text, true);
  execute 'set local role authenticated';
  out := out || 'other_uid=' || public.has_plus(p) || ' ';
  out := out || 'own_uid=' || public.has_plus(o) || ' ';
  insert into public.building_comments (bbl, user_id, author, body)
  values ('1000000000', o, 'Find A Crib Team', 'test') returning author into a;
  out := out || 'author=' || a || ' ';
  execute 'reset role';
  perform set_config('request.jwt.claims', json_build_object('sub', p, 'role', 'authenticated')::text, true);
  execute 'set local role authenticated';
  out := out || 'self_plus=' || public.has_plus(p) || ' ';
  execute 'reset role';
  execute 'set local role service_role';
  out := out || 'service_role=' || public.has_plus(p) || ' ';
  raise exception 'RESULT %', out;
end $$;
