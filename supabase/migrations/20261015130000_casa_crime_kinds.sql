-- Your Casa crime alerts (owner, 2026-10-15: "people should be able to
-- configure alerts on the type of crime that happens"). The NYPD publishes
-- complaints and shootings quarterly, so these fire when a new release
-- includes the chosen kinds within half a mile of the watched building.
-- crime_kinds holds Casa's own keys (casa_alerts.CRIME_KINDS); crime_seen is
-- the newest NYPD date already announced; lat/lng come from GeoSearch.
alter table public.casa_watches
  add column if not exists lat double precision,
  add column if not exists lng double precision,
  add column if not exists crime_kinds text[] not null default '{}',
  add column if not exists crime_seen date;
alter table public.casa_watches drop constraint if exists casa_watches_lat_lng;
alter table public.casa_watches add constraint casa_watches_lat_lng
  check ((lat is null and lng is null) or (lat between 40.4 and 41.0 and lng between -74.3 and -73.6));
notify pgrst, 'reload schema';
