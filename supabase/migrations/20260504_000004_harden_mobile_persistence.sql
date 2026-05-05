-- Hardening migration for mobile Supabase Auth persistence.
-- Run after the initial schema migration.
-- It keeps user-owned rows protected while ensuring the mobile client can
-- save watchlist items and completed recommendation sessions for auth.uid().

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'saved_movies_user_id_tmdb_id_key'
      and conrelid = 'public.saved_movies'::regclass
  ) then
    alter table public.saved_movies
      add constraint saved_movies_user_id_tmdb_id_key unique (user_id, tmdb_id);
  end if;
end $$;

create index if not exists saved_movies_user_payload_id_idx
  on public.saved_movies(user_id, ((movie_payload ->> 'id')));

alter table public.conversations enable row level security;
alter table public.messages enable row level security;
alter table public.recommendations enable row level security;
alter table public.saved_movies enable row level security;

drop policy if exists "conversations_select_own" on public.conversations;
create policy "conversations_select_own"
on public.conversations for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists "conversations_insert_own" on public.conversations;
create policy "conversations_insert_own"
on public.conversations for insert
to authenticated
with check (auth.uid() = user_id);

drop policy if exists "conversations_update_own" on public.conversations;
create policy "conversations_update_own"
on public.conversations for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "messages_select_own" on public.messages;
create policy "messages_select_own"
on public.messages for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists "messages_insert_own" on public.messages;
create policy "messages_insert_own"
on public.messages for insert
to authenticated
with check (
  auth.uid() = user_id
  and exists (
    select 1
    from public.conversations c
    where c.id = conversation_id
      and c.user_id = auth.uid()
  )
);

drop policy if exists "messages_delete_own" on public.messages;
create policy "messages_delete_own"
on public.messages for delete
to authenticated
using (auth.uid() = user_id);

drop policy if exists "recommendations_select_own" on public.recommendations;
create policy "recommendations_select_own"
on public.recommendations for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists "recommendations_insert_own" on public.recommendations;
create policy "recommendations_insert_own"
on public.recommendations for insert
to authenticated
with check (auth.uid() = user_id);

drop policy if exists "recommendations_delete_own" on public.recommendations;
create policy "recommendations_delete_own"
on public.recommendations for delete
to authenticated
using (auth.uid() = user_id);

drop policy if exists "saved_movies_select_own" on public.saved_movies;
create policy "saved_movies_select_own"
on public.saved_movies for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists "saved_movies_insert_own" on public.saved_movies;
create policy "saved_movies_insert_own"
on public.saved_movies for insert
to authenticated
with check (auth.uid() = user_id);

drop policy if exists "saved_movies_update_own" on public.saved_movies;
create policy "saved_movies_update_own"
on public.saved_movies for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "saved_movies_delete_own" on public.saved_movies;
create policy "saved_movies_delete_own"
on public.saved_movies for delete
to authenticated
using (auth.uid() = user_id);
