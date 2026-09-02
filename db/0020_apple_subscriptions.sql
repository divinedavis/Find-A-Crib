-- Find A Crib Plus bought through the App Store (StoreKit auto-renewable
-- subscription, 2026-09-02). The iOS app cannot unlock Plus without offering
-- it as an in-app purchase (App Store Review 3.1.3(b)), so subscriptions now
-- come from two providers. has_plus() is unchanged: it reads status +
-- current_period_end, which both providers write. Rows are written ONLY by
-- the service role — Stripe via the stripe-webhook function, Apple via the
-- apple-subscription function after it verifies Apple's signed transaction.
alter table public.subscriptions add column if not exists provider text not null default 'stripe';
alter table public.subscriptions add column if not exists apple_original_transaction_id text;
alter table public.subscriptions add column if not exists apple_product_id text;
alter table public.subscriptions add column if not exists apple_environment text;
-- One Apple subscription belongs to one account: a second account presenting
-- the same transaction (a shared Apple ID, or a replayed token) must not gain
-- Plus. Partial so Stripe rows (null) are unaffected.
create unique index if not exists subscriptions_apple_otid_uidx
  on public.subscriptions (apple_original_transaction_id) where apple_original_transaction_id is not null;
notify pgrst, 'reload schema';
