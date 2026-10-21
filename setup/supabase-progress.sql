-- TeamBid: the table for team progress, team changes and document requests (all rows are encrypted by the page).
-- Run once in Supabase: SQL Editor > New query > paste > Run.
-- Append-only: the public (anon) key may read and add rows, never change or delete them.

create table if not exists public.teambid_progress (
  id bigint generated always as identity primary key,
  team text not null check (length(team) < 100),
  item text not null check (length(item) < 100),
  payload text not null check (length(payload) < 8000),
  created_at timestamptz not null default now()
);
create index if not exists teambid_progress_team on public.teambid_progress (team, created_at);
alter table public.teambid_progress enable row level security;
drop policy if exists "team can read" on public.teambid_progress;
drop policy if exists "team can add" on public.teambid_progress;
create policy "team can read" on public.teambid_progress for select to anon using (true);
create policy "team can add"  on public.teambid_progress for insert to anon with check (true);
revoke update, delete on public.teambid_progress from anon, authenticated;
grant select, insert on public.teambid_progress to anon;
