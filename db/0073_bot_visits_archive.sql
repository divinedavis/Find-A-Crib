-- Bot traffic that got past the browser isBot() guard, moved out of the
-- analytics tables so every dashboard/report number stops counting it.
-- 2026-11-02: a Tencent Cloud (AS132203) crawler with rotating IPs and stock
-- Chrome User-Agents ran the page JS and wrote one fresh visitor per page
-- (~50/hour from 16:00 UTC; 246 that day, 7 earlier). Rows were matched to its
-- nginx requests by path + time. Moving (not deleting) keeps it reversible:
--   insert into public.visits (visitor_id,user_id,path,referrer,created_at)
--   select visitor_id,user_id,path,referrer,created_at from public.visits_bot_archive;
-- nginx now 403s that ASN (infra repo, conf.d/findacrib_blocked_asn.conf).
create table if not exists public.visits_bot_archive (
  like public.visits,
  reason      text not null,
  archived_at timestamptz not null default now()
);
create table if not exists public.events_bot_archive (
  like public.events,
  reason      text not null,
  archived_at timestamptz not null default now()
);
alter table public.visits_bot_archive enable row level security;
alter table public.events_bot_archive enable row level security;
revoke all on public.visits_bot_archive, public.events_bot_archive from anon, authenticated;
grant all on public.visits_bot_archive, public.events_bot_archive to service_role;
