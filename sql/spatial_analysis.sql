create table if not exists public.spatial_analysis (
    snapshot_id integer primary key
        references public.spatial_snapshots(id) on delete cascade,
    zone_id text not null
        references public.spatial_zones(zone_id),
    scene_id text not null,
    acquired_at timestamptz not null,
    summary jsonb not null,
    hulls jsonb not null,
    flags jsonb not null,
    method text not null,
    computed_at timestamptz not null default now()
);

alter table public.spatial_analysis enable row level security;
