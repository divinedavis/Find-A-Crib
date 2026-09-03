-- Borough alerts: optional rent / income filters.
--
-- max_rent  — only alert when the listing's LOWEST advertised rent is at or
--             under this ($/mo).
-- income    — only alert when the household income sits inside the listing's
--             stated band ($/yr).
-- Both nullable = no filter. A listing with no figure for a set filter still
-- goes out (the dispatcher decides that; re-rental boards rarely print rents
-- and a silent drop would be worse than one extra email).

alter table public.lottery_alert_subs
  add column if not exists max_rent int
    check (max_rent is null or max_rent between 100 and 20000),
  add column if not exists income int
    check (income is null or income between 1000 and 2000000);

drop function if exists public.lottery_alerts_subscribe(text, text[], text[]);
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
    where k = any(array['lottery','rerental']);
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

drop function if exists public.lottery_alerts_recipients();
create or replace function public.lottery_alerts_recipients()
returns table (id uuid, email text, boroughs text[], kinds text[], token uuid,
               welcomed_at timestamptz, last_sent_at timestamptz,
               max_rent int, income int)
language sql security definer set search_path = public as $$
  select id, email, boroughs, kinds, token, welcomed_at, last_sent_at, max_rent, income
    from lottery_alert_subs
   where unsubscribed_at is null
   order by created_at;
$$;

revoke all on function public.lottery_alerts_subscribe(text, text[], text[], int, int) from public, anon, authenticated;
revoke all on function public.lottery_alerts_recipients() from public, anon, authenticated;
grant execute on function public.lottery_alerts_subscribe(text, text[], text[], int, int) to service_role;
grant execute on function public.lottery_alerts_recipients() to service_role;
