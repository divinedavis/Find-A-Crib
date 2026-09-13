-- Alert-email clicks (2026-09-12).
--
-- Every link in a borough-alert email (alert, welcome, nudge, Tuesday weekly)
-- goes through findacrib.com/api/alerts/go, which calls alert_click_record and
-- 302s to the real page. Before this the only measure was ?src=alert landings
-- on the map, and the listing links go straight to Housing Connect / agent
-- sites, so a click on the thing the email is actually about was invisible.
--
-- One row per click. `is_bot` marks mail-gateway link scanners and HEAD
-- requests (decided in the API) — kept rather than dropped so the filter can
-- be audited, excluded from the dashboard. Rows go with the subscriber.

create table if not exists public.alert_clicks (
  id          bigint generated always as identity primary key,
  sub_id      uuid not null references public.lottery_alert_subs(id) on delete cascade,
  email_kind  text not null check (email_kind in ('alert','welcome','nudge','weekly')),
  target_host text not null default '' check (char_length(target_host) <= 253),
  is_bot      boolean not null default false,
  clicked_at  timestamptz not null default now()
);
create index if not exists alert_clicks_clicked_at_idx on public.alert_clicks (clicked_at);
create index if not exists alert_clicks_sub_idx on public.alert_clicks (sub_id);

alter table public.alert_clicks enable row level security;
revoke all on public.alert_clicks from public, anon, authenticated;
grant select, insert, delete on public.alert_clicks to service_role;

-- A signed link can be replayed by whoever holds the email, so the table is
-- bounded per subscriber per day; past the cap the click still redirects, it
-- just isn't stored. An unknown subscriber (unsubscribed + deleted) is a no-op.
create or replace function public.alert_click_record(
  p_sub uuid, p_kind text, p_host text, p_bot boolean)
returns boolean language plpgsql security definer set search_path = public as $$
begin
  if p_kind not in ('alert','welcome','nudge','weekly') then
    return false;
  end if;
  if not exists (select 1 from lottery_alert_subs where id = p_sub) then
    return false;
  end if;
  if (select count(*) from alert_clicks
       where sub_id = p_sub and clicked_at > now() - interval '1 day') >= 100 then
    return false;
  end if;
  insert into alert_clicks (sub_id, email_kind, target_host, is_bot)
  values (p_sub, p_kind, left(coalesce(p_host, ''), 253), coalesce(p_bot, false));
  return true;
end $$;

revoke all on function public.alert_click_record(uuid, text, text, boolean) from public, anon, authenticated;
grant execute on function public.alert_click_record(uuid, text, text, boolean) to service_role;
