-- Security audit 2026-09-25: DB hygiene.
--
-- 1. ios_app_users had RLS off. Nothing reads it as anon/authenticated today
--    (no grants to either role; only the SECURITY DEFINER functions
--    dashboard_users() and refresh_ios_app_users(), owned by postgres, touch
--    it), so the gap is latent — but one default-privilege grant would have
--    exposed every row. RLS on with no policies = deny for API roles; the
--    table owner and service_role bypass it, so both functions keep working.
alter table public.ios_app_users enable row level security;

-- 2. comment_blocks / comment_reports carried Supabase's default TRUNCATE
--    grant. RLS does not apply to TRUNCATE, so any signed-in user could wipe
--    every user's blocks and every moderation report in one statement.
revoke truncate on public.comment_blocks  from authenticated, anon;
revoke truncate on public.comment_reports from authenticated, anon;
