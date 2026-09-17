-- public.events had no index on user_id. dashboard_users() runs several
-- correlated subqueries per account over that table — last sign-in, share
-- count, most-viewed borough, and an EXISTS to decide whether the account has
-- done anything at all — so with 140 accounts and 177,806 events (66 MB,
-- ~8,600/day) every dashboard load meant a few hundred sequential scans. On
-- 2026-09-17 it crossed the statement timeout: /api/dashboard-users returned
-- 503 and findacrib.com/dashboard/users/ showed "Couldn't load users", while
-- the main dashboard (which filters events by created_at, and had an index for
-- it) kept working.
--
-- Partial, because only 15,159 of those rows carry a user_id at all: the two
-- indexes together are under 800 kB. Measured after: dashboard_users() went
-- from a timeout (>30 s) to 0.2 s.
create index if not exists events_user_event_idx
  on public.events (user_id, event) where user_id is not null;
create index if not exists events_user_created_idx
  on public.events (user_id, created_at desc) where user_id is not null;
