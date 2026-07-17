-- Harden the write-grant surface (security review 2026-07-17). RLS already
-- blocks these writes (verified: a user self-inserting an active subscription
-- gets 403), but the grants shouldn't exist at all — defense in depth so a
-- future permissive policy can't silently expose them.

-- subscriptions: only the Stripe webhook (service_role) writes; clients read own.
revoke insert, update, delete on public.subscriptions from anon, authenticated;

-- agent_phones: fully private — reachable only through get_agent_phone() (a
-- SECURITY DEFINER function that runs as the owner, so revoking is invisible to it).
revoke all on public.agent_phones from anon, authenticated;

-- hpd_contacts: public read only; written by build_hpd_contacts.py (service_role).
revoke insert, update, delete on public.hpd_contacts from anon, authenticated;

-- categories / saved_searches: owner-scoped, only ever touched by an authenticated
-- user (or, for shared folders, the get_shared_folder() definer function). anon
-- never reads or writes them directly.
revoke select, insert, update, delete on public.categories from anon;
revoke select, insert, update, delete on public.saved_searches from anon;
