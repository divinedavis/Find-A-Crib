-- Remove page views logged by Google's AdSense crawler (Mediapartners-Google),
-- which renders pages with JavaScript and was not caught by the client-side
-- bot test until 2026-09-26. Fingerprint (visits carries no user agent):
-- anonymous visitors with exactly one visit and no events, landing inside a
-- minute holding >= 4 such visitors, at least half of them on SEO pages.
-- Rows are copied to public.visits_bot_removed first, so this is reversible.
begin;
create table if not exists public.visits_bot_removed as
  select v.*, now() as removed_at, ''::text as reason from public.visits v where false;
alter table public.visits_bot_removed enable row level security;
revoke all on public.visits_bot_removed from anon, authenticated;
with one as (select v.visitor_id, min(v.created_at) t, min(v.path) p from public.visits v where v.user_id is null group by 1 having count(*) = 1),
quiet as (select o.* from one o where not exists (select 1 from public.events e where e.visitor_id = o.visitor_id)),
mins as (select date_trunc('minute', t) m, count(*) n, count(*) filter (where p <> '/') seo from quiet group by 1),
burst as (select m from mins where n >= 4 and seo * 2 >= n),
fake as (select q.visitor_id from quiet q join burst b on date_trunc('minute', q.t) = b.m),
moved as (
  insert into public.visits_bot_removed
  select v.*, now(), 'adsense crawler burst (Mediapartners-Google), 2026-09-26 cleanup'
  from public.visits v join fake f using (visitor_id)
  returning visitor_id)
delete from public.visits v using moved m where v.visitor_id = m.visitor_id;
select (select count(*) from public.visits_bot_removed) backed_up;
commit;
