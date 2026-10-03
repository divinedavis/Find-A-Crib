-- The AI gateway (api_server.py) asks has_plus() with the service key.
grant execute on function public.has_plus(uuid) to service_role;
notify pgrst, 'reload schema';
