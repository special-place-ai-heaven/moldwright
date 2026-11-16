create table public.factory_projects (
    workspace_id bigint not null references public.workspaces (id) on delete cascade,
    repo text not null check (repo ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9_.-]{1,100}$'),
    link text not null check (char_length(link) <= 300),
    base_branch text check (char_length(base_branch) <= 200),
    added_at timestamptz not null default now(),
    added_by text not null check (char_length(added_by) <= 100),
    active boolean not null default false,
    wanted boolean not null default false,
    ready boolean not null default false,
    check_asked_at timestamptz,
    checked_at timestamptz,
    readiness jsonb not null default '[]'::jsonb,
    selected_at timestamptz,
    selected_by text check (char_length(selected_by) <= 100),
    left_at timestamptz,
    primary key (workspace_id, repo)
);

create unique index factory_projects_one_active_idx on public.factory_projects (workspace_id) where active;
create unique index factory_projects_one_wanted_idx on public.factory_projects (workspace_id) where wanted;

alter table public.factory_projects enable row level security;
revoke all on table public.factory_projects from anon, authenticated;
grant select, insert, update, delete on table public.factory_projects to service_role;

alter table public.workspaces add column factory_owner uuid references auth.users (id) on delete set null;

update public.workspaces w
set factory_owner = (
    select m.user_id from public.workspace_members m
    where m.workspace_id = w.id and m.role = 'admin'
    order by m.created_at asc, m.user_id asc
    limit 1
);
