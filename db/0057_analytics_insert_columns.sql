-- 0057: anon analytics inserts can no longer pick id or created_at
-- (security audit 2026-10-07, L12).
--
-- events/visits take anonymous INSERTs by design (first-party analytics, with
-- size CHECKs since 0009). But the INSERT grant covered every column, so a
-- caller could backdate rows into any dashboard window (created_at) or
-- pre-claim upcoming sequence ids, making later real inserts fail on the
-- primary key. Neither client sends either column (index.html track()/visit,
-- ios Analytics.swift), so the grant narrows to the columns they do send and
-- the defaults fill the rest.
--
-- Rate limiting is not done here: these inserts go straight to Supabase, not
-- through our nginx, and a per-row trigger lookup on the hottest table would
-- cost more than the abuse it stops.
revoke insert on public.events from anon, authenticated;
grant insert (visitor_id, user_id, event, props, path) on public.events to anon, authenticated;
revoke insert on public.visits from anon, authenticated;
grant insert (visitor_id, user_id, path, referrer) on public.visits to anon, authenticated;
notify pgrst, 'reload schema';
