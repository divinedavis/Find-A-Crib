-- Per-person monthly AI budget (owner, 2026-10-12: "lets do a per person
-- budget of $1"). ai_gateway.allow() refuses a member's AI calls once their
-- own spend this New York month reaches AI_USER_MONTHLY_MICROS ($1). Same
-- month boundary as ai_spend_month(). Rules-only features cost 0 and never
-- count against it.
create or replace function public.ai_user_spend_month(p_user uuid)
returns bigint
language sql
stable
security definer
set search_path = public
as $$
  select coalesce(sum(cost_micros), 0)::bigint from ai_usage
   where user_id = p_user
     and created_at >= date_trunc('month', now() at time zone 'America/New_York') at time zone 'America/New_York';
$$;
revoke all on function public.ai_user_spend_month(uuid) from public, anon, authenticated;
grant execute on function public.ai_user_spend_month(uuid) to service_role;
