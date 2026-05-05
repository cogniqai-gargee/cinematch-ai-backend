-- CineMatch AI initial Supabase schema.
-- Apply in Supabase Dashboard > SQL Editor.
-- RLS notes:
-- - All user-owned tables have row level security enabled.
-- - Policies below allow authenticated users to read/write only their own rows.
-- - Backend service-role access, if added later, bypasses RLS and should never be exposed to Expo.

create extension if not exists pgcrypto;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table if not exists public.profiles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique references auth.users(id) on delete cascade,
  display_name text,
  avatar_url text,
  location text,
  preferred_language text,
  onboarding_completed boolean not null default false,
  taste_summary jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text,
  status text not null default 'active' check (status in ('active', 'archived')),
  extracted_preferences jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('user', 'assistant', 'system')),
  content text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.movie_preferences (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  conversation_id uuid references public.conversations(id) on delete set null,
  genres text[] not null default '{}'::text[],
  moods text[] not null default '{}'::text[],
  liked_movies text[] not null default '{}'::text[],
  disliked_movies text[] not null default '{}'::text[],
  watchlist_signals text[] not null default '{}'::text[],
  preferred_languages text[] not null default '{}'::text[],
  runtime_min integer,
  runtime_max integer,
  occasion text,
  vibe_tags text[] not null default '{}'::text[],
  raw_preferences jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint movie_preferences_runtime_check
    check (
      runtime_min is null
      or runtime_max is null
      or runtime_min <= runtime_max
    )
);

create table if not exists public.recommendations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  conversation_id uuid references public.conversations(id) on delete set null,
  movie_preference_id uuid references public.movie_preferences(id) on delete set null,
  tmdb_id integer,
  title text not null,
  release_year integer,
  poster_url text,
  backdrop_url text,
  genres text[] not null default '{}'::text[],
  runtime_minutes integer,
  language text,
  synopsis text,
  rank integer not null,
  match_score integer not null check (match_score between 0 and 100),
  reasoning text,
  provider text not null default 'mock',
  model text,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.saved_movies (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  recommendation_id uuid references public.recommendations(id) on delete set null,
  tmdb_id integer,
  title text not null,
  release_year integer,
  poster_url text,
  backdrop_url text,
  genres text[] not null default '{}'::text[],
  runtime_minutes integer,
  language text,
  saved_reason text,
  match_score integer check (match_score between 0 and 100),
  movie_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, tmdb_id)
);

create index if not exists profiles_user_id_idx
  on public.profiles(user_id);

create index if not exists conversations_user_id_created_at_idx
  on public.conversations(user_id, created_at desc);

create index if not exists messages_conversation_id_created_at_idx
  on public.messages(conversation_id, created_at asc);

create index if not exists messages_user_id_created_at_idx
  on public.messages(user_id, created_at desc);

create index if not exists movie_preferences_user_id_created_at_idx
  on public.movie_preferences(user_id, created_at desc);

create index if not exists movie_preferences_conversation_id_idx
  on public.movie_preferences(conversation_id);

create index if not exists recommendations_user_id_created_at_idx
  on public.recommendations(user_id, created_at desc);

create index if not exists recommendations_conversation_id_rank_idx
  on public.recommendations(conversation_id, rank asc);

create index if not exists recommendations_tmdb_id_idx
  on public.recommendations(tmdb_id);

create index if not exists saved_movies_user_id_created_at_idx
  on public.saved_movies(user_id, created_at desc);

create index if not exists saved_movies_tmdb_id_idx
  on public.saved_movies(tmdb_id);

drop trigger if exists set_profiles_updated_at on public.profiles;
create trigger set_profiles_updated_at
before update on public.profiles
for each row execute function public.set_updated_at();

drop trigger if exists set_conversations_updated_at on public.conversations;
create trigger set_conversations_updated_at
before update on public.conversations
for each row execute function public.set_updated_at();

drop trigger if exists set_movie_preferences_updated_at on public.movie_preferences;
create trigger set_movie_preferences_updated_at
before update on public.movie_preferences
for each row execute function public.set_updated_at();

drop trigger if exists set_saved_movies_updated_at on public.saved_movies;
create trigger set_saved_movies_updated_at
before update on public.saved_movies
for each row execute function public.set_updated_at();

alter table public.profiles enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;
alter table public.movie_preferences enable row level security;
alter table public.recommendations enable row level security;
alter table public.saved_movies enable row level security;

drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own"
on public.profiles for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists "profiles_insert_own" on public.profiles;
create policy "profiles_insert_own"
on public.profiles for insert
to authenticated
with check (auth.uid() = user_id);

drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own"
on public.profiles for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "profiles_delete_own" on public.profiles;
create policy "profiles_delete_own"
on public.profiles for delete
to authenticated
using (auth.uid() = user_id);

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

drop policy if exists "conversations_delete_own" on public.conversations;
create policy "conversations_delete_own"
on public.conversations for delete
to authenticated
using (auth.uid() = user_id);

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

drop policy if exists "messages_update_own" on public.messages;
create policy "messages_update_own"
on public.messages for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "messages_delete_own" on public.messages;
create policy "messages_delete_own"
on public.messages for delete
to authenticated
using (auth.uid() = user_id);

drop policy if exists "movie_preferences_select_own" on public.movie_preferences;
create policy "movie_preferences_select_own"
on public.movie_preferences for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists "movie_preferences_insert_own" on public.movie_preferences;
create policy "movie_preferences_insert_own"
on public.movie_preferences for insert
to authenticated
with check (auth.uid() = user_id);

drop policy if exists "movie_preferences_update_own" on public.movie_preferences;
create policy "movie_preferences_update_own"
on public.movie_preferences for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "movie_preferences_delete_own" on public.movie_preferences;
create policy "movie_preferences_delete_own"
on public.movie_preferences for delete
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

drop policy if exists "recommendations_update_own" on public.recommendations;
create policy "recommendations_update_own"
on public.recommendations for update
to authenticated
using (auth.uid() = user_id)
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
