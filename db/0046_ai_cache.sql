-- 2026-10-03: AI answers that are the same for every viewer (a building's
-- report card, a listing's application help) are kept for a week, so the
-- second visitor costs nothing. Service role only.
create table if not exists public.ai_cache (
  feature text not null,
  key text not null,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  primary key (feature, key)
);
alter table public.ai_cache enable row level security;
revoke all on table public.ai_cache from anon, authenticated;
notify pgrst, 'reload schema';
