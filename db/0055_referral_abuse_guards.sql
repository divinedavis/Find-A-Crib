-- 0055: referral farming guards (security audit 2026-10-07, M2).
--
-- redeem_referral() gave 2 months of Plus to BOTH accounts and only checked
-- that the redeemer was <30 minutes old and never referred before. Sign-up
-- auto-confirms with no captcha, so one person could mint accounts from one
-- browser and stack months on their main account indefinitely. Email
-- verification is ruled out (owner rule), so instead:
--
--   1. caps per referrer: at most 3 credited referrals in any 30 days and 10
--      ever. Past the cap the code still works as a link, but nobody is
--      granted anything ('referrer_limit');
--   2. same network: the redeemer's IP (Cloudflare's cf-connecting-ip, which
--      Supabase forwards to PostgREST) must not match any IP the referrer used
--      to fetch their link in the last 30 days ('same_network');
--   3. per-IP rate limit: 5 redeem attempts an hour and 2 successful
--      redemptions a day from one IP ('rate_limited').
--
-- IPs are stored only as salted SHA-256 hashes (salt in private.app_salt,
-- unreachable through the Data API) and pruned after 30 days. When no IP
-- header is present (service calls, tests) checks 2-3 are skipped; the caps
-- still apply. The web client already treats any {ok:false} silently.

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create table if not exists private.app_salt (
  id   int primary key default 1 check (id = 1),
  salt text not null default encode(extensions.gen_random_bytes(32), 'hex')
);
insert into private.app_salt (id) values (1) on conflict do nothing;

create table if not exists private.referral_ip_log (
  id       bigserial primary key,
  user_id  uuid,
  ip_hash  text not null,
  kind     text not null check (kind in ('link', 'attempt', 'redeemed')),
  at       timestamptz not null default now()
);
create index if not exists referral_ip_log_hash_at on private.referral_ip_log (ip_hash, kind, at);
create index if not exists referral_ip_log_user_at on private.referral_ip_log (user_id, kind, at);
revoke all on all tables in schema private from public, anon, authenticated;
revoke all on all sequences in schema private from public, anon, authenticated;

-- Salted hash of the caller's IP as Cloudflare saw it, or null.
create or replace function private.request_ip_hash()
returns text
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  h  jsonb;
  ip text;
begin
  begin
    h := nullif(current_setting('request.headers', true), '')::jsonb;
  exception when others then
    return null;
  end;
  ip := coalesce(h->>'cf-connecting-ip',
                 nullif(trim(split_part(coalesce(h->>'x-forwarded-for', ''), ',', 1)), ''));
  if ip is null or ip = '' then
    return null;
  end if;
  return encode(extensions.digest((select salt from private.app_salt where id = 1) || '|' || ip, 'sha256'), 'hex');
end;
$$;
revoke all on function private.request_ip_hash() from public, anon, authenticated;

-- Record the referrer's network each time they fetch their link.
create or replace function public.get_or_create_referral()
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  uid uuid := auth.uid();
  c   text;
  ih  text := private.request_ip_hash();
begin
  if uid is null then
    raise exception 'not authenticated';
  end if;
  if ih is not null and not exists (
       select 1 from private.referral_ip_log
        where user_id = uid and ip_hash = ih and kind = 'link' and at > now() - interval '1 day') then
    insert into private.referral_ip_log (user_id, ip_hash, kind) values (uid, ih, 'link');
  end if;
  select code into c from public.referrals
    where referrer_id = uid and status = 'active' limit 1;
  if c is not null then
    return c;
  end if;
  c := lower(substr(replace(gen_random_uuid()::text, '-', ''), 1, 9));
  insert into public.referrals (code, referrer_id) values (c, uid);
  return c;
end;
$$;

create or replace function public.redeem_referral(p_code text)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  uid  uuid := auth.uid();
  ref  public.referrals%rowtype;
  born timestamptz;
  ih   text := private.request_ip_hash();
begin
  if uid is null then
    return jsonb_build_object('ok', false, 'reason', 'not_authenticated');
  end if;
  delete from private.referral_ip_log where at < now() - interval '30 days';
  if ih is not null then
    if (select count(*) from private.referral_ip_log
         where ip_hash = ih and kind = 'attempt' and at > now() - interval '1 hour') >= 5
       or (select count(*) from private.referral_ip_log
         where ip_hash = ih and kind = 'redeemed' and at > now() - interval '1 day') >= 2 then
      return jsonb_build_object('ok', false, 'reason', 'rate_limited');
    end if;
    insert into private.referral_ip_log (user_id, ip_hash, kind) values (uid, ih, 'attempt');
  end if;
  -- only a brand-new account can redeem (blocks existing users pasting a link)
  select created_at into born from auth.users where id = uid;
  if born is null or born < now() - interval '30 minutes' then
    return jsonb_build_object('ok', false, 'reason', 'not_a_new_signup');
  end if;
  -- a user can only ever be referred once
  if exists (select 1 from public.referrals where referred_id = uid) then
    return jsonb_build_object('ok', false, 'reason', 'already_referred');
  end if;
  select * into ref from public.referrals
    where code = p_code and status = 'active' for update;
  if ref.code is null then
    return jsonb_build_object('ok', false, 'reason', 'invalid_or_used');
  end if;
  if ref.referrer_id = uid then
    return jsonb_build_object('ok', false, 'reason', 'self_referral');
  end if;
  if ih is not null and exists (
       select 1 from private.referral_ip_log
        where user_id = ref.referrer_id and ip_hash = ih and kind in ('link', 'attempt', 'redeemed')) then
    return jsonb_build_object('ok', false, 'reason', 'same_network');
  end if;
  if (select count(*) from public.referrals
       where referrer_id = ref.referrer_id and status = 'redeemed'
         and redeemed_at > now() - interval '30 days') >= 3
     or (select count(*) from public.referrals
       where referrer_id = ref.referrer_id and status = 'redeemed') >= 10 then
    return jsonb_build_object('ok', false, 'reason', 'referrer_limit');
  end if;
  update public.referrals
     set status = 'redeemed', referred_id = uid, redeemed_at = now()
   where code = ref.code and status = 'active';
  if ih is not null then
    insert into private.referral_ip_log (user_id, ip_hash, kind) values (uid, ih, 'redeemed');
  end if;
  perform public.grant_referral_plus(ref.referrer_id);   -- inviter
  perform public.grant_referral_plus(uid);               -- new friend
  return jsonb_build_object('ok', true);
end;
$$;

revoke all on function public.redeem_referral(text) from public, anon;
revoke all on function public.get_or_create_referral() from public, anon;
grant execute on function public.redeem_referral(text) to authenticated, service_role;
grant execute on function public.get_or_create_referral() to authenticated, service_role;

notify pgrst, 'reload schema';
