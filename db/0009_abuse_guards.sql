-- Abuse guards (security hardening 2026-07-16).
--
-- 1. Cap saved_buildings per user. Saving is free with any account, so a
--    disposable signup could insert unlimited rows to bloat the table. A
--    real renter saves dozens; 1000 is a generous ceiling.
-- 2. Bound the size of anonymous analytics writes. visits/events accept
--    anon inserts by design; without a shape guard a script can pump giant
--    rows. Cap the text/jsonb payloads so abuse can't balloon row size.

create or replace function public.cap_saved_buildings()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if (select count(*) from public.saved_buildings where user_id = new.user_id) >= 1000 then
    raise exception 'saved building limit reached';
  end if;
  return new;
end;
$$;
drop trigger if exists trg_cap_saved_buildings on public.saved_buildings;
create trigger trg_cap_saved_buildings
  before insert on public.saved_buildings
  for each row execute function public.cap_saved_buildings();

-- Reject oversized analytics rows (defense in depth alongside RLS insert-only).
alter table public.visits drop constraint if exists visits_sane_size;
alter table public.visits add constraint visits_sane_size check (
  char_length(coalesce(path, '')) <= 2048
  and char_length(coalesce(referrer, '')) <= 2048
  and char_length(coalesce(visitor_id, '')) <= 128
);
alter table public.events drop constraint if exists events_sane_size;
alter table public.events add constraint events_sane_size check (
  char_length(coalesce(event, '')) <= 64
  and char_length(coalesce(path, '')) <= 2048
  and char_length(coalesce(visitor_id, '')) <= 128
  and pg_column_size(props) <= 4096
);
