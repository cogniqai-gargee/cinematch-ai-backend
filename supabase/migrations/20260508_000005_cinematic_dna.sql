-- Stores each user's evolving Cinematic DNA
-- Updated automatically every time the user watches, rates, saves, or chats

create table if not exists public.cinematic_dna (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references auth.users(id) on delete cascade,
  genres          jsonb not null default '[]',
  moods           jsonb not null default '[]',
  languages       jsonb not null default '[]',
  avoid_genres    jsonb not null default '[]',
  liked_titles    jsonb not null default '[]',
  disliked_titles jsonb not null default '[]',
  era_preference  text,
  avg_rating      numeric(3,1),
  total_watched   integer not null default 0,
  total_saved     integer not null default 0,
  last_updated    timestamptz not null default now(),
  created_at      timestamptz not null default now(),
  unique (user_id)
);

alter table public.cinematic_dna enable row level security;

create policy "Users can read own dna"
  on public.cinematic_dna for select
  using (auth.uid() = user_id);

create policy "Users can insert own dna"
  on public.cinematic_dna for insert
  with check (auth.uid() = user_id);

create policy "Users can update own dna"
  on public.cinematic_dna for update
  using (auth.uid() = user_id);