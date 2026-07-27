-- One-time paid Building Reports.
--
-- A purchase creates a row; the token is the only credential needed to read the
-- report back, so the row must never be reachable through the public Data API.
-- That is a deliberate departure from this project's usual habit of granting
-- anon + authenticated on every new table: anon SELECT here would let anyone
-- page through the table and harvest every token (and every buyer's email).
-- Only the service role — that is, the API server — touches this.

create table if not exists public.building_reports (
  id                uuid primary key default gen_random_uuid(),
  token             text not null unique,
  bbl               text not null,
  email             text,
  stripe_session_id text unique,
  status            text not null default 'pending'
                    check (status in ('pending', 'paid', 'refunded')),
  created_at        timestamptz not null default now(),
  paid_at           timestamptz,
  last_viewed_at    timestamptz,
  view_count        int not null default 0
);

create index if not exists building_reports_token_idx   on public.building_reports (token);
create index if not exists building_reports_session_idx on public.building_reports (stripe_session_id);
create index if not exists building_reports_email_idx   on public.building_reports (lower(email));

-- RLS on with zero policies = deny everything. The service role bypasses RLS,
-- which is exactly the access we want and the only access we want.
alter table public.building_reports enable row level security;

revoke all on public.building_reports from anon, authenticated;
grant all on public.building_reports to service_role;
