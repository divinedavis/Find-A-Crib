-- Landlord / managing-agent search  (search box: "acme realty llc")
--
-- Why: 46% of settled searches returned zero results, and two of them were
-- people typing an LLC name ("211 clinton st. realty co. llc") into a box that
-- only understood addresses. The owner/manager/officer names already live in
-- this table -- they were just never searchable.
--
-- `names` is a stored generated column holding all three names in one lowercase
-- string so a single trigram index serves the whole lookup. ILIKE '%foo%' can
-- never use a btree index; a GIN trigram index is the only thing that makes a
-- substring match over 46k rows fast enough to run on every keystroke.
create extension if not exists pg_trgm;

-- ' | ' separates the three names on purpose: it keeps a two-word query from
-- matching across a boundary ("realty llc lewis" spanning owner into officer),
-- and lets the browser split the row back into the individual names it needs to
-- label a suggestion.
alter table public.hpd_contacts
  add column if not exists names text
  -- concat_ws() is only STABLE, which a generated column rejects; plain ||
  -- over coalesce() is immutable and does the same job.
  generated always as (
    lower(coalesce(owner   ->> 'name', '') || ' | ' ||
          coalesce(manager ->> 'name', '') || ' | ' ||
          coalesce(officer ->> 'name', ''))
  ) stored;

create index if not exists hpd_contacts_names_trgm
  on public.hpd_contacts using gin (names gin_trgm_ops);

-- The Data API only sees what is granted (see the standing rule: always GRANT
-- in migrations). Table-level SELECT already covers the new column, but state
-- it explicitly so a future `revoke all` + replay lands in the same place.
grant select on public.hpd_contacts to anon, authenticated;

-- Security, same change: every one of these tables was handing `authenticated`
-- the TRUNCATE privilege, and TRUNCATE is not subject to row-level security --
-- an RLS policy that limits a signed-in user to `auth.uid() = user_id` does
-- nothing to stop `truncate`. PostgREST exposes no TRUNCATE verb so there is no
-- known reachable path today, but the grant is pure downside: nothing in the
-- app has ever used it, and any future SECURITY INVOKER function or direct
-- connection would inherit it. REFERENCES/TRIGGER are equally unused.
revoke truncate, trigger, references on public.hpd_contacts   from anon, authenticated;
revoke truncate, trigger, references on public.visits         from anon, authenticated;
revoke truncate, trigger, references on public.events         from anon, authenticated;
revoke truncate, trigger, references on public.saved_searches from anon, authenticated;
revoke truncate, trigger, references on public.categories     from anon, authenticated;
revoke truncate, trigger, references on public.subscriptions  from anon, authenticated;
