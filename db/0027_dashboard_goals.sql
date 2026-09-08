-- 2026-09-07: goals that move. When daily / weekly / monthly active reaches
-- its goal, the moment is recorded and the goal rises 30% (rounded up to a
-- ten). The dashboard draws each recorded goal as a marker on the bar with
-- the date it was reached. Written only by api_server.py (service role) as
-- the owner's dashboard loads.
create table if not exists public.dashboard_goals (
  metric      text primary key,
  goal        integer not null,
  history     jsonb not null default '[]'::jsonb,   -- [{goal, value, achieved_at}]
  updated_at  timestamptz not null default now()
);
alter table public.dashboard_goals enable row level security;
revoke all on public.dashboard_goals from public, anon, authenticated;
grant select, insert, update on public.dashboard_goals to service_role;

create or replace function public.dashboard_goal_check(p_metric text, p_value numeric, p_default integer)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  r dashboard_goals;
  v_goal int;
  v_hist jsonb;
begin
  insert into dashboard_goals (metric, goal) values (p_metric, p_default)
    on conflict (metric) do nothing;
  select * into r from dashboard_goals where metric = p_metric;
  v_goal := r.goal; v_hist := r.history;
  -- p_value null = read only. A jump that clears several goals at once
  -- records each of them; the cap is a guard, not a limit anyone will hit.
  while p_value is not null and p_value >= v_goal and jsonb_array_length(v_hist) < 60 loop
    v_hist := v_hist || jsonb_build_object('goal', v_goal, 'value', p_value, 'achieved_at', now());
    v_goal := (ceil(v_goal * 1.3 / 10.0) * 10)::int;
  end loop;
  if v_goal <> r.goal then
    update dashboard_goals set goal = v_goal, history = v_hist, updated_at = now() where metric = p_metric;
  end if;
  return jsonb_build_object('goal', v_goal, 'history', v_hist);
end;
$$;
revoke all on function public.dashboard_goal_check(text, numeric, integer) from public, anon, authenticated;
grant execute on function public.dashboard_goal_check(text, numeric, integer) to service_role;
