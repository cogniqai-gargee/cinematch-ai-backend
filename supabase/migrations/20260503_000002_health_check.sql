-- Lightweight database probe for backend health checks.
-- This lets the backend verify Supabase connectivity without depending on
-- user-owned RLS tables or authenticated user context.

create or replace function public.health_check()
returns integer
language sql
security definer
set search_path = public
as $$
  select 1;
$$;

grant execute on function public.health_check() to anon;
grant execute on function public.health_check() to authenticated;
