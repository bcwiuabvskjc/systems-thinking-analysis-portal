-- Run this entire file in Supabase SQL Editor before deploying the app.
create extension if not exists pgcrypto;

create table if not exists public.groups (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_by uuid not null references auth.users(id) on delete cascade,
  join_code text not null unique default encode(gen_random_bytes(6),'hex'),
  created_at timestamptz not null default now()
);
create table if not exists public.group_members (
  group_id uuid not null references public.groups(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null default 'member' check (role in ('owner','member')),
  created_at timestamptz not null default now(),
  primary key (group_id,user_id)
);
create table if not exists public.projects (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  owner_id uuid not null references auth.users(id) on delete cascade,
  workspace_type text not null default 'personal' check (workspace_type in ('personal','group')),
  group_id uuid references public.groups(id) on delete cascade,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint group_project_requires_group check ((workspace_type='personal' and group_id is null) or (workspace_type='group' and group_id is not null))
);
create index if not exists projects_owner_idx on public.projects(owner_id);
create index if not exists projects_group_idx on public.projects(group_id);
create index if not exists group_members_user_idx on public.group_members(user_id);

-- SECURITY DEFINER helpers avoid recursive RLS lookups on group_members.
create or replace function public.is_group_member(gid uuid, uid uuid default auth.uid())
returns boolean language sql stable security definer set search_path=public
as $$ select exists (select 1 from public.group_members gm where gm.group_id=gid and gm.user_id=uid); $$;
create or replace function public.is_group_owner(gid uuid, uid uuid default auth.uid())
returns boolean language sql stable security definer set search_path=public
as $$ select exists (select 1 from public.group_members gm where gm.group_id=gid and gm.user_id=uid and gm.role='owner'); $$;
create or replace function public.is_group_creator(gid uuid, uid uuid default auth.uid())
returns boolean language sql stable security definer set search_path=public
as $$ select exists (select 1 from public.groups g where g.id=gid and g.created_by=uid); $$;
create or replace function public.join_group_by_code(code text)
returns uuid language plpgsql security definer set search_path=public
as $$ declare found_group uuid; begin
  if auth.uid() is null then raise exception 'You must be logged in.'; end if;
  select id into found_group from public.groups where lower(join_code)=lower(trim(code));
  if found_group is null then raise exception 'Invalid group join code.'; end if;
  insert into public.group_members(group_id,user_id,role) values(found_group,auth.uid(),'member') on conflict (group_id,user_id) do nothing;
  return found_group;
end; $$;
revoke all on function public.is_group_member(uuid,uuid) from public;
revoke all on function public.is_group_owner(uuid,uuid) from public;
revoke all on function public.is_group_creator(uuid,uuid) from public;
revoke all on function public.join_group_by_code(text) from public;
grant execute on function public.is_group_member(uuid,uuid) to authenticated;
grant execute on function public.is_group_owner(uuid,uuid) to authenticated;
grant execute on function public.is_group_creator(uuid,uuid) to authenticated;
grant execute on function public.join_group_by_code(text) to authenticated;

alter table public.groups enable row level security;
alter table public.group_members enable row level security;
alter table public.projects enable row level security;

drop policy if exists "members can view their groups" on public.groups;
create policy "members can view their groups" on public.groups for select to authenticated
using (public.is_group_member(id,auth.uid()));
drop policy if exists "authenticated users can create groups" on public.groups;
create policy "authenticated users can create groups" on public.groups for insert to authenticated
with check (created_by=auth.uid());
drop policy if exists "owners can update groups" on public.groups;
create policy "owners can update groups" on public.groups for update to authenticated
using (public.is_group_owner(id,auth.uid())) with check (public.is_group_owner(id,auth.uid()));
drop policy if exists "owners can delete groups" on public.groups;
create policy "owners can delete groups" on public.groups for delete to authenticated
using (public.is_group_owner(id,auth.uid()));

drop policy if exists "members can view memberships" on public.group_members;
create policy "members can view memberships" on public.group_members for select to authenticated
using (user_id=auth.uid() or public.is_group_member(group_id,auth.uid()));
drop policy if exists "creator can add self as owner" on public.group_members;
create policy "creator can add self as owner" on public.group_members for insert to authenticated
with check (user_id=auth.uid() and role='owner' and public.is_group_creator(group_id,auth.uid()));
drop policy if exists "group owners can add members" on public.group_members;
create policy "group owners can add members" on public.group_members for insert to authenticated
with check (public.is_group_owner(group_id,auth.uid()));
drop policy if exists "owners can remove members and users can leave" on public.group_members;
create policy "owners can remove members and users can leave" on public.group_members for delete to authenticated
using (user_id=auth.uid() or public.is_group_owner(group_id,auth.uid()));

drop policy if exists "users can view their personal projects and group projects" on public.projects;
create policy "users can view their personal projects and group projects" on public.projects for select to authenticated
using ((workspace_type='personal' and owner_id=auth.uid()) or (workspace_type='group' and public.is_group_member(group_id,auth.uid())));
drop policy if exists "users can create personal or group projects" on public.projects;
create policy "users can create personal or group projects" on public.projects for insert to authenticated
with check ((workspace_type='personal' and owner_id=auth.uid() and group_id is null) or (workspace_type='group' and owner_id=auth.uid() and public.is_group_member(group_id,auth.uid())));
drop policy if exists "members can update projects in their workspace" on public.projects;
create policy "members can update projects in their workspace" on public.projects for update to authenticated
using ((workspace_type='personal' and owner_id=auth.uid()) or (workspace_type='group' and public.is_group_member(group_id,auth.uid())))
with check ((workspace_type='personal' and owner_id=auth.uid() and group_id is null) or (workspace_type='group' and public.is_group_member(group_id,auth.uid())));
drop policy if exists "owners can delete projects in their workspace" on public.projects;
create policy "owners can delete projects in their workspace" on public.projects for delete to authenticated
using ((workspace_type='personal' and owner_id=auth.uid()) or (workspace_type='group' and public.is_group_owner(group_id,auth.uid())));
