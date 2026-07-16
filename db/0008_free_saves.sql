-- Saving buildings is now FREE for signed-in users (reverses migration 0003's
-- has_plus gate): saves are the signup hook for ad traffic. Still Plus-gated:
-- listing alert emails, agent phones, research, folders, saved searches.

drop policy if exists own_insert on public.saved_buildings;
create policy own_insert on public.saved_buildings
  for insert with check (auth.uid() = user_id);
