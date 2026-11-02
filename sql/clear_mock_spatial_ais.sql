begin;

-- AIS provenance was not stored on prior spatial_analysis rows. Clear all derived
-- analyses so the startup bootstrap can rebuild them from live AIS. Keep snapshots
-- and satellite image objects intact.
alter table public.spatial_analysis
    add column if not exists ais_vessels jsonb not null default '[]'::jsonb;

create table if not exists public.spatial_startup_state (
    startup_key text primary key,
    status text not null check (status in ('pending', 'running', 'complete', 'failed')),
    started_at timestamptz,
    completed_at timestamptz,
    error text
);

alter table public.spatial_startup_state enable row level security;

insert into public.spatial_startup_state (startup_key, status)
values ('live_ais_bootstrap', 'pending')
on conflict (startup_key) do update
set status = 'pending',
    started_at = null,
    completed_at = null,
    error = null;

delete from public.spatial_analysis;

update public.spatial_snapshots
set status = 'fetched',
    analyzed_at = null
where status is distinct from 'fetched';

commit;
