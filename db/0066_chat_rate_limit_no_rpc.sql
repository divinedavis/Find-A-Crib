-- chat_rate_limit() is a trigger function (chat_messages insert). Triggers
-- fire whatever the caller's EXECUTE rights, so nobody needs it over
-- /rest/v1/rpc; the 10/19 Supabase security check flagged anon + authenticated.
revoke execute on function public.chat_rate_limit() from public, anon, authenticated;
