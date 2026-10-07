-- Rollback-only check of db/0055 against the live database (scratch users are
-- created inside the block and the final RAISE undoes everything).
--   scripts/sql.sh tests/sql/referral_guards_test.sql   ->  error text holds the verdicts
do $$
declare
  ref_u uuid := gen_random_uuid();
  out text := '';
  code text;
  r jsonb;
  i int;
  newu uuid;
begin
  insert into auth.users (id, instance_id, aud, role, email, created_at, updated_at)
  values (ref_u, '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated',
          'reftest-' || ref_u || '@example.invalid', now() - interval '10 days', now());
  -- referrer fetches a link from 1.1.1.1
  perform set_config('request.jwt.claims', json_build_object('sub', ref_u, 'role', 'authenticated')::text, true);
  perform set_config('request.headers', '{"cf-connecting-ip":"1.1.1.1"}', true);
  code := public.get_or_create_referral();

  -- 1) same network: new account redeeming from the referrer's IP
  newu := gen_random_uuid();
  insert into auth.users (id, instance_id, aud, role, email, created_at, updated_at)
  values (newu, '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'n0-' || newu || '@example.invalid', now(), now());
  perform set_config('request.jwt.claims', json_build_object('sub', newu, 'role', 'authenticated')::text, true);
  r := public.redeem_referral(code);
  out := out || 'same_ip=' || (r->>'reason') || ' ';

  -- 2) different IPs: three credited, the fourth hits the 30-day cap
  for i in 1..4 loop
    perform set_config('request.jwt.claims', json_build_object('sub', ref_u, 'role', 'authenticated')::text, true);
    perform set_config('request.headers', '{"cf-connecting-ip":"1.1.1.1"}', true);
    code := public.get_or_create_referral();
    newu := gen_random_uuid();
    insert into auth.users (id, instance_id, aud, role, email, created_at, updated_at)
    values (newu, '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'n' || i || '-' || newu || '@example.invalid', now(), now());
    perform set_config('request.jwt.claims', json_build_object('sub', newu, 'role', 'authenticated')::text, true);
    perform set_config('request.headers', json_build_object('cf-connecting-ip', '9.9.9.' || i)::text, true);
    r := public.redeem_referral(code);
    out := out || 'r' || i || '=' || coalesce(r->>'reason', 'ok') || ' ';
  end loop;

  -- 3) per-IP: a third success from one IP in a day is refused
  perform set_config('request.headers', '{"cf-connecting-ip":"5.5.5.5"}', true);
  for i in 1..6 loop
    newu := gen_random_uuid();
    insert into auth.users (id, instance_id, aud, role, email, created_at, updated_at)
    values (newu, '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'x' || i || '-' || newu || '@example.invalid', now(), now());
    perform set_config('request.jwt.claims', json_build_object('sub', newu, 'role', 'authenticated')::text, true);
    r := public.redeem_referral('nosuchcode');
    out := out || 'a' || i || '=' || coalesce(r->>'reason', 'ok') || ' ';
  end loop;

  raise exception 'RESULT %', out;
end $$;
