-- Follow-up sequence for Building Report buyers.
--
-- These people paid and handed over an email at the single highest-intent
-- moment in the funnel, so they are the right audience to build a lifecycle
-- around — not the handful of free accounts. Everything here exists to make
-- that sequence honest and stoppable:
--
--   sent_steps      which steps have gone out, so a re-run of the daily job
--                   never mails anyone twice. The job is idempotent by design;
--                   this is what makes that true across restarts.
--   unsub_token     a credential distinct from the report token. The report
--                   token is the buyer's access to a thing they paid for, and
--                   an unsubscribe link gets crawled by mail scanners — those
--                   two must not be the same string.
--   unsubscribed_at set once and honoured forever, including on re-purchase.

alter table public.building_reports
  add column if not exists sent_steps      jsonb not null default '[]'::jsonb,
  add column if not exists unsub_token     text,
  add column if not exists unsubscribed_at timestamptz;

create unique index if not exists building_reports_unsub_token_idx
  on public.building_reports (unsub_token) where unsub_token is not null;

-- Existing rows predate the column; give them a token so they can opt out too.
update public.building_reports
   set unsub_token = encode(gen_random_bytes(18), 'hex')
 where unsub_token is null;

-- Grants unchanged from 0002: service_role only. Deliberately no anon access —
-- anon SELECT would expose buyer emails and both token columns.
grant all on public.building_reports to service_role;
