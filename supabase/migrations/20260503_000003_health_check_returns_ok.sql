-- RLS-safe Supabase health probe for the FastAPI backend.
-- This function avoids reading protected app tables such as public.profiles.

drop function if exists public.health_check();

create or replace function public.health_check()
returns text
language sql
security definer
set search_path = public
as $$
  select 'ok';
$$;

grant execute on function public.health_check() to anon;
grant execute on function public.health_check() to authenticated;
