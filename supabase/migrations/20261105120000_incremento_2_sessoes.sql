create table public.sessions (
    session_id text primary key,
    content_version text not null,
    create_request_id text not null,
    state jsonb not null,
    revision integer not null,
    scene_revision integer not null,
    phase text not null,
    session_status text not null,
    turn_epoch integer not null,
    last_event_seq integer not null,
    active_attempt_id text,
    connection_generation integer not null,
    controller_id text not null,
    created_at timestamptz not null,
    updated_at timestamptz not null,
    expires_at timestamptz not null,
    constraint uq_sessions_create_request_id unique (create_request_id),
    constraint ck_sessions_revision check (revision >= 0),
    constraint ck_sessions_connection_generation check (connection_generation >= 1)
);

create table public.session_credentials (
    token_hash text primary key,
    session_id text not null references public.sessions (session_id) on delete cascade,
    actor text not null,
    created_at timestamptz not null,
    constraint ck_session_credentials_actor check (actor = 'learner')
);

create table public.attempts (
    session_id text not null references public.sessions (session_id) on delete cascade,
    attempt_id text not null,
    kind text not null,
    item_id text not null,
    status text not null,
    outcome text,
    assistance_level text not null,
    support_resources jsonb not null,
    updated_revision integer not null,
    constraint pk_attempts primary key (session_id, attempt_id)
);

create table public.session_events (
    event_id text primary key,
    session_id text not null references public.sessions (session_id) on delete cascade,
    event_seq integer not null,
    revision integer not null,
    type text not null,
    actor text not null,
    command_id text,
    attempt_id text,
    occurred_at timestamptz not null,
    data jsonb not null,
    constraint uq_session_events_session_seq unique (session_id, event_seq)
);

create table public.command_results (
    session_id text not null references public.sessions (session_id) on delete cascade,
    command_id text not null,
    kind text not null,
    body_hash text not null,
    actor text not null,
    principal_id text not null,
    http_status integer not null,
    response jsonb not null,
    revision integer not null,
    created_at timestamptz not null,
    constraint pk_command_results primary key (session_id, command_id),
    constraint ck_command_results_kind check (kind in ('command', 'claim_control'))
);

create table public.render_receipts (
    session_id text not null references public.sessions (session_id) on delete cascade,
    receipt_id text not null,
    effect_id text not null,
    command_id text not null,
    scene_revision integer not null,
    connection_generation integer not null,
    status text not null,
    outcome text not null,
    received_at timestamptz not null,
    constraint pk_render_receipts primary key (session_id, receipt_id),
    constraint ck_render_receipts_outcome check (outcome in ('accepted', 'stale'))
);

create table public.artifacts (
    artifact_id text primary key,
    session_id text not null references public.sessions (session_id) on delete cascade,
    attempt_id text not null,
    purpose text not null,
    version integer not null,
    content_hash text,
    object_key text,
    created_at timestamptz not null,
    expires_at timestamptz not null,
    constraint uq_artifacts_attempt_purpose_version unique (session_id, attempt_id, purpose, version),
    constraint ck_artifacts_purpose check (purpose in ('source', 'notebook')),
    constraint ck_artifacts_version check (version >= 1)
);

create table public.analysis_jobs (
    job_id text primary key,
    session_id text not null references public.sessions (session_id) on delete cascade,
    artifact_id text not null references public.artifacts (artifact_id) on delete cascade,
    request_id text not null,
    status text not null,
    executions integer not null default 0,
    applied boolean not null default false,
    error_code text,
    created_at timestamptz not null,
    updated_at timestamptz not null,
    constraint uq_analysis_jobs_session_request unique (session_id, request_id),
    constraint ck_analysis_jobs_status check (
        status in ('queued', 'running', 'ready', 'needs_clarification', 'failed', 'superseded')
    )
);

create table public.observations (
    observation_id text primary key,
    job_id text not null references public.analysis_jobs (job_id) on delete cascade,
    session_id text not null references public.sessions (session_id) on delete cascade,
    attempt_id text not null,
    artifact_id text not null references public.artifacts (artifact_id) on delete cascade,
    document jsonb not null,
    created_at timestamptz not null,
    constraint uq_observations_job_id unique (job_id)
);

-- Só o backend acessa estas tabelas (conexão de serviço, que ignora RLS). RLS ligado e nenhuma
-- policy: os papéis anon e authenticated do Supabase não leem nem escrevem nada.
alter table public.sessions enable row level security;
alter table public.session_credentials enable row level security;
alter table public.attempts enable row level security;
alter table public.session_events enable row level security;
alter table public.command_results enable row level security;
alter table public.render_receipts enable row level security;
alter table public.artifacts enable row level security;
alter table public.analysis_jobs enable row level security;
alter table public.observations enable row level security;
