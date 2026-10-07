-- 2026-10-06: the moving DAU/WAU/MAU goals (db/0027) are the owner
-- dashboard's own state, not Find A Crib data. They moved with the dashboard
-- to its own API (repo divinedavis/owner-dashboard, api/goals.py -> goals.json
-- on 159.203.110.79); the three rows were copied and verified first, and a
-- pg_dump of the table is archived on the owner's Mac
-- (~/Documents/Archived/dashboard-split-2026-10-06/). api_server.py stopped
-- calling dashboard_goal_check() in the same change.
drop function if exists public.dashboard_goal_check(text, numeric, integer);
drop table if exists public.dashboard_goals;
