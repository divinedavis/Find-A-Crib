-- 0023: a third alert kind, "voucher" — a landlord soliciting Section 8 /
-- voucher tenants on AffordableHousing.com (the s8.json feed the map's
-- "Accepting vouchers" mode already shows). The iOS app's Alerts button
-- subscribes to it from the voucher view; the web /alerts/ form gets a
-- checkbox. Everything else about a subscription is unchanged.

alter table public.lottery_alert_subs
  drop constraint if exists lottery_alert_subs_kinds_ck;
alter table public.lottery_alert_subs
  add constraint lottery_alert_subs_kinds_ck
    check (cardinality(kinds) between 1 and 3
           and kinds <@ array['lottery','rerental','voucher']::text[]);

create or replace function public.lottery_alerts_subscribe(
  p_email text, p_boroughs text[], p_kinds text[] default '{lottery,rerental}',
  p_max_rent int default null, p_income int default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_email text := lower(trim(p_email));
  v_boros text[];
  v_kinds text[];
  v_today int;
  v_row lottery_alert_subs;
begin
  select array_agg(distinct b) into v_boros
    from unnest(p_boroughs) b where b = any(array['M','Bk','Q','Bx','SI']);
  select array_agg(distinct k) into v_kinds
    from unnest(coalesce(p_kinds, '{lottery,rerental}')) k
    where k = any(array['lottery','rerental','voucher']);
  if v_boros is null then
    return jsonb_build_object('ok', false, 'reason', 'no_borough');
  end if;
  if v_kinds is null then
    v_kinds := '{lottery,rerental}';
  end if;
  if v_email !~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$' or length(v_email) > 254 then
    return jsonb_build_object('ok', false, 'reason', 'invalid_email');
  end if;
  if p_max_rent is not null and p_max_rent not between 100 and 20000 then
    return jsonb_build_object('ok', false, 'reason', 'bad_rent');
  end if;
  if p_income is not null and p_income not between 1000 and 2000000 then
    return jsonb_build_object('ok', false, 'reason', 'bad_income');
  end if;
  select count(*) into v_today from lottery_alert_subs where created_at >= current_date;
  if v_today >= 1000 and not exists (select 1 from lottery_alert_subs where email = v_email) then
    return jsonb_build_object('ok', false, 'reason', 'signup_cap');
  end if;
  insert into lottery_alert_subs (email, boroughs, kinds, max_rent, income)
  values (v_email, v_boros, v_kinds, p_max_rent, p_income)
  on conflict (email) do update
     set boroughs = excluded.boroughs,
         kinds = excluded.kinds,
         max_rent = excluded.max_rent,
         income = excluded.income,
         unsubscribed_at = null,
         updated_at = now()
  returning * into v_row;
  return jsonb_build_object('ok', true, 'boroughs', to_jsonb(v_row.boroughs),
                            'kinds', to_jsonb(v_row.kinds),
                            'max_rent', v_row.max_rent, 'income', v_row.income);
end;
$$;
revoke all on function public.lottery_alerts_subscribe(text, text[], text[], int, int) from public, anon, authenticated;
grant execute on function public.lottery_alerts_subscribe(text, text[], text[], int, int) to service_role;
