-- Comments in the iPhone app are user-generated content, so App Review
-- Guideline 1.2 applies: people need a way to report a comment and to block
-- the person who wrote it, and we have to act on reports. These two tables are
-- what the app writes; the owner reads comment_reports to moderate.
--
-- Applied to production 2026-09-20 through the Management API SQL endpoint.
create table if not exists public.comment_reports (
  id uuid primary key default gen_random_uuid(),
  comment_id uuid not null references public.building_comments(id) on delete cascade,
  reporter_id uuid not null references auth.users(id) on delete cascade,
  reason text,
  created_at timestamptz not null default now(),
  unique (comment_id, reporter_id)
);

create table if not exists public.comment_blocks (
  user_id uuid not null references auth.users(id) on delete cascade,
  blocked_id uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (user_id, blocked_id)
);

alter table public.comment_reports enable row level security;
alter table public.comment_blocks  enable row level security;

-- House convention (see 0010_harden_grants): grant to the role, let RLS decide.
grant select, insert on public.comment_reports to authenticated;
grant select, insert, delete on public.comment_blocks to authenticated;
grant select on public.comment_reports, public.comment_blocks to anon;

drop policy if exists reports_insert_own on public.comment_reports;
create policy reports_insert_own on public.comment_reports
  for insert to authenticated with check (auth.uid() = reporter_id);

-- A reporter may see their own reports; nobody else reads them from the client.
drop policy if exists reports_read_own on public.comment_reports;
create policy reports_read_own on public.comment_reports
  for select to authenticated using (auth.uid() = reporter_id);

-- A block list is private to the person who made it.
drop policy if exists blocks_own on public.comment_blocks;
create policy blocks_own on public.comment_blocks
  for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);

notify pgrst, 'reload schema';
