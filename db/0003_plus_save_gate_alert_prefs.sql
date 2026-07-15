-- Plus ($4.99/mo) now also gates saving buildings and email alerts.
--
-- 1. saved_buildings INSERT requires an active subscription (has_plus), so the
--    client-side paywall can't be bypassed with a direct Data API call.
--    Existing rows stay readable/deletable by their owners.
-- 2. alert_prefs gets a user-facing surface via definer RPCs (the table itself
--    keeps NO anon/authenticated grants): the profile modal reads/writes the
--    alert toggle through them. Enabling requires Plus; disabling never does.
--    No row yet = alerts on (matches notify_saved_listings.py, which auto-
--    creates the row on first send).

drop policy if exists own_insert on public.saved_buildings;
create policy own_insert on public.saved_buildings
  for insert with check (auth.uid() = user_id and public.has_plus(auth.uid()));

create or replace function public.get_alerts_enabled()
returns boolean language sql stable security definer set search_path = public as $$
  select coalesce(
    (select unsubscribed_at is null from alert_prefs where user_id = auth.uid()),
    true);
$$;

create or replace function public.set_alerts_enabled(p_on boolean)
returns boolean language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then
    raise exception 'not signed in';
  end if;
  if p_on and not public.has_plus(auth.uid()) then
    raise exception 'plus required';
  end if;
  insert into alert_prefs (user_id, unsubscribed_at)
  values (auth.uid(), case when p_on then null else now() end)
  on conflict (user_id) do update set unsubscribed_at = excluded.unsubscribed_at;
  return p_on;
end;
$$;

revoke all on function public.get_alerts_enabled() from public;
revoke all on function public.set_alerts_enabled(boolean) from public;
grant execute on function public.get_alerts_enabled() to authenticated;
grant execute on function public.set_alerts_enabled(boolean) to authenticated;
