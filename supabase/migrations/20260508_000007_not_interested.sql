-- Permanently hides movies the user is not interested in

create table if not exists public.not_interested (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  tmdb_id    integer not null,
  title      text not null,
  created_at timestamptz not null default now(),
  unique (user_id, tmdb_id)
);

alter table public.not_interested enable row level security;

create policy "Users can read own not_interested"
  on public.not_interested for select
  using (auth.uid() = user_id);

create policy "Users can insert own not_interested"
  on public.not_interested for insert
  with check (auth.uid() = user_id);

create policy "Users can delete own not_interested"
  on public.not_interested for delete
  using (auth.uid() = user_id);

create index if not exists not_interested_user_id_idx on public.not_interested(user_id);