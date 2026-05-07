-- Stores movies the user has marked as watched, with optional rating

create table if not exists public.watched_movies (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references auth.users(id) on delete cascade,
  tmdb_id         integer not null,
  title           text not null,
  poster_url      text,
  backdrop_url    text,
  genres          jsonb not null default '[]',
  language        text,
  year            integer,
  rating          numeric(3,1),       -- user's own rating, 1.0–5.0
  tmdb_rating     numeric(4,1),       -- TMDB's vote_average
  synopsis        text,
  watched_at      timestamptz not null default now(),
  created_at      timestamptz not null default now(),
  unique (user_id, tmdb_id)
);

alter table public.watched_movies enable row level security;

create policy "Users can read own watched"
  on public.watched_movies for select
  using (auth.uid() = user_id);

create policy "Users can insert own watched"
  on public.watched_movies for insert
  with check (auth.uid() = user_id);

create policy "Users can update own watched"
  on public.watched_movies for update
  using (auth.uid() = user_id);

create policy "Users can delete own watched"
  on public.watched_movies for delete
  using (auth.uid() = user_id);

-- Index for fast lookup
create index if not exists watched_movies_user_id_idx on public.watched_movies(user_id);