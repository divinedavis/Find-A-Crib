-- Addresses Find A Crib must stop mailing (owner, 2026-10-20: "im seeing a
-- lot of delivery status notification (delay) emails, why?"). Every alert
-- job mailed the same dead addresses daily — testing@/tester@/testers@gmail
-- (don't exist), mahad.h@maio.com (rejected), a "gmail.ckm" typo, two full
-- inboxes — and each bounce landed in divine@findacrib.com.
--
-- mail_bounce_sort.py fills this from the bounce notices it files away;
-- growth/emailkit.send() skips any row with suppressed = true. Hard bounces
-- (no such user, no such domain, inbox full AND inactive) suppress at once;
-- soft ones (inbox full, delays) after 3. Service role only.
create table if not exists public.email_suppressions (
  email text primary key check (email = lower(email)),
  kind text not null check (kind in ('hard', 'soft')),
  reason text,
  bounces int not null default 1,
  suppressed boolean not null default false,
  first_at timestamptz not null default now(),
  last_at timestamptz not null default now()
);
alter table public.email_suppressions enable row level security;
revoke all on public.email_suppressions from anon, authenticated;

-- One call per bounce: counts it and decides. Soft bounces suppress on the
-- third; a hard one at once; a hard row never goes back to soft.
create or replace function public.email_bounce_record(p_email text, p_kind text, p_reason text)
returns boolean language sql security definer set search_path = public as $$
  insert into email_suppressions as s (email, kind, reason, suppressed)
  values (lower(p_email), p_kind, left(p_reason, 300), p_kind = 'hard')
  on conflict (email) do update set
    bounces = s.bounces + 1,
    kind = case when s.kind = 'hard' or excluded.kind = 'hard' then 'hard' else 'soft' end,
    reason = excluded.reason,
    last_at = now(),
    suppressed = s.suppressed or excluded.kind = 'hard' or s.bounces + 1 >= 3
  returning suppressed;
$$;
revoke execute on function public.email_bounce_record(text, text, text) from public, anon, authenticated;
grant execute on function public.email_bounce_record(text, text, text) to service_role;
