-- 0058: log of App Store Server Notifications V2 (security audit 2026-10-07,
-- L13). Written only by the apple-notifications edge function (service role)
-- AFTER Apple's JWS verified. Holds no address or receipt — ids, types and
-- the outcome — so an unmatched paying subscriber ("unmatched") is visible
-- instead of silently dropped. Not exposed to anon/authenticated.
create table if not exists public.apple_notifications (
  notification_uuid       text primary key,
  notification_type       text not null,
  subtype                 text,
  environment             text,
  original_transaction_id text,
  product_id              text,
  expires_at              timestamptz,
  signed_at               timestamptz,
  user_id                 uuid,
  outcome                 text not null,
  received_at             timestamptz not null default now()
);
create index if not exists apple_notifications_otid on public.apple_notifications (original_transaction_id);
alter table public.apple_notifications enable row level security;
revoke all on public.apple_notifications from anon, authenticated;
grant all on public.apple_notifications to service_role;
notify pgrst, 'reload schema';
