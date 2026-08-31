-- Take EXECUTE away from anon on the SECURITY DEFINER functions that have no
-- signed-out use. Found while adding 0016: every one of these was still
-- anon-callable with only the publishable key.
--
-- Why they were: Supabase's ALTER DEFAULT PRIVILEGES grants EXECUTE on each new
-- public function to anon and authenticated BY NAME. The `revoke ... from
-- public` these migrations used removes PUBLIC's implicit grant and leaves the
-- explicit anon one untouched, so the revoke reads as if it worked and does
-- nothing. The roles have to be named.
--
-- None of these leaked building or account data — each one gates on
-- has_plus(auth.uid()) or bails when auth.uid() is null, and auth.uid() is null
-- for anon. The exception, and the reason this is worth a migration rather than
-- a note: has_plus(uid) takes the user id as an ARGUMENT instead of reading
-- auth.uid(), so anyone holding the publishable key could ask whether a given
-- user id was a paying subscriber. A caller needs a real uuid to learn anything,
-- but that is a subscription-status oracle and it should never have been open.

-- Plus-gated readers: safe for anon today (they return null), still shouldn't be
-- reachable — the gate should be the grant as well as the function body.
revoke execute on function public.has_plus(uuid)            from anon;
revoke execute on function public.get_research(text)        from anon;
revoke execute on function public.get_agent_phone(text)     from anon;

-- auth.uid()-only: these already raise or return not_authenticated for anon.
revoke execute on function public.get_alerts_enabled()      from anon;
revoke execute on function public.set_alerts_enabled(boolean) from anon;
revoke execute on function public.get_or_create_referral()  from anon;
revoke execute on function public.redeem_referral(text)     from anon;

-- Trigger functions. A trigger fires as the table owner and never consults
-- EXECUTE, so nothing calls these by name and nothing should be able to.
revoke execute on function public.cap_saved_buildings()     from anon, authenticated;
revoke execute on function public.guard_shared_tree()       from anon, authenticated;

-- DELIBERATELY LEFT ANON-CALLABLE — every one of these is a signed-out flow and
-- revoking it would break a shipped link:
--   get_shared_folder(uuid)      — findacrib.com/#folder=<token>, read-only share
--   unsubscribe_alerts(uuid)     — one-click unsubscribe from a saved-search email
--   unsubscribe_lifecycle(uuid)  — same, for the lifecycle series
-- All three take an unguessable token and return only what that token names.

-- Second pass. The first one revoked from anon and left four functions still
-- anon-callable, because their EXECUTE was granted to PUBLIC (`=X/postgres` in
-- proacl), which anon inherits. The trap runs in both directions: a revoke has
-- to name PUBLIC *and* the roles, or one of the two paths survives it.
revoke execute on function public.has_plus(uuid)         from public;
revoke execute on function public.get_agent_phone(text)  from public;
revoke execute on function public.cap_saved_buildings()  from public;
revoke execute on function public.guard_shared_tree()    from public;

-- Owner-scoped: resets the share token on a category the caller owns, and bails
-- when auth.uid() is null. No signed-out use.
revoke execute on function public.reset_share_token(uuid) from public, anon;
