begin;

-- Reset the one-time startup bootstrap. It fetches missing zone imagery first,
-- then rebuilds all active-zone analyses from AIS at each latest scene time.
-- Keep satellite snapshots and image objects intact.
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
values ('spatial_image_ais_bootstrap_v2', 'pending')
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
