-- Systems Thinking Analysis Portal: individual-account-only Supabase schema.
-- Run once in the SQL Editor of a NEW Supabase project.
-- No group tables or public/anon table access are created.

create table if not exists public.projects (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    name text not null default 'Untitled project',
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists projects_user_id_updated_at_idx
    on public.projects (user_id, updated_at desc);

alter table public.projects enable row level security;

-- Remove old policies with these names if this script is re-run.
drop policy if exists "Users can read their own projects" on public.projects;
drop policy if exists "Users can create their own projects" on public.projects;
drop policy if exists "Users can update their own projects" on public.projects;
drop policy if exists "Users can delete their own projects" on public.projects;

create policy "Users can read their own projects"
    on public.projects for select to authenticated
    using ((select auth.uid()) = user_id);

create policy "Users can create their own projects"
    on public.projects for insert to authenticated
    with check ((select auth.uid()) = user_id);

create policy "Users can update their own projects"
    on public.projects for update to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create policy "Users can delete their own projects"
    on public.projects for delete to authenticated
    using ((select auth.uid()) = user_id);

-- Ensure the public/anonymous roles cannot access project rows.
revoke all on table public.projects from anon, public;

-- Grant access only to signed-in users. RLS policies above restrict rows to auth.uid().
grant usage on schema public to authenticated;
grant select, insert, update, delete on table public.projects to authenticated;

-- Verify after running:
-- select tablename, rowsecurity from pg_tables
-- where schemaname='public' and tablename='projects';
-- Expected: projects | true
