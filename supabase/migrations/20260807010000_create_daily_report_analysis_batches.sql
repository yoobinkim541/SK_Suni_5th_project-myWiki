create table if not exists public.daily_report_analysis_batches (
    id uuid primary key default gen_random_uuid(),
    workspace_id uuid not null references public.workspaces(id) on delete cascade,
    report_date date not null,
    document_version_ids jsonb not null default '[]'::jsonb,
    status text not null check (status in ('running', 'completed')),
    started_at timestamptz not null,
    completed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (workspace_id, report_date)
);

create index if not exists daily_report_analysis_batches_report_lookup_idx
    on public.daily_report_analysis_batches (workspace_id, report_date, status);

alter table public.daily_report_analysis_batches enable row level security;
