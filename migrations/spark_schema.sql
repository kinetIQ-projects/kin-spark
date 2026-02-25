-- =============================================================================
-- Kin Spark — Database Schema Migration
-- Run via Supabase SQL Editor
-- =============================================================================

-- Enable pgvector if not already enabled
create extension if not exists vector;

-- =============================================================================
-- 1. spark_clients — Client registry
-- =============================================================================
create table if not exists spark_clients (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references auth.users(id) on delete set null,
    name text not null,
    slug text not null unique,
    api_key_hash text not null unique,
    settling_config jsonb not null default '{}'::jsonb,
    max_turns int not null default 20,
    rate_limit_rpm int not null default 30,
    active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index idx_spark_clients_api_key_hash on spark_clients (api_key_hash);
create index idx_spark_clients_slug on spark_clients (slug);
create index idx_spark_clients_user_id on spark_clients (user_id);

-- =============================================================================
-- 2. spark_documents — Ingested knowledge chunks
-- =============================================================================
create table if not exists spark_documents (
    id uuid primary key default gen_random_uuid(),
    client_id uuid not null references spark_clients(id) on delete cascade,
    content text not null,
    embedding vector(2000),
    title text,
    source_type text not null default 'text',
    source_url text,
    chunk_index int not null default 0,
    content_hash text not null,
    created_at timestamptz not null default now()
);

-- Unique constraint for deduplication
alter table spark_documents
    add constraint uq_spark_documents_client_hash unique (client_id, content_hash);

-- HNSW index for vector similarity search
create index idx_spark_documents_embedding on spark_documents
    using hnsw (embedding vector_cosine_ops)
    with (m = 16, ef_construction = 64);

create index idx_spark_documents_client on spark_documents (client_id);
create index idx_spark_documents_source_url on spark_documents (client_id, source_url);

-- =============================================================================
-- 3. spark_conversations — Session tracking
-- =============================================================================
create table if not exists spark_conversations (
    id uuid primary key default gen_random_uuid(),
    client_id uuid not null references spark_clients(id) on delete cascade,
    session_token text not null unique,
    ip_address text not null,
    visitor_fingerprint text,
    turn_count int not null default 0,
    state text not null default 'active',
    expires_at timestamptz not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index idx_spark_conversations_session on spark_conversations (session_token);
create index idx_spark_conversations_client on spark_conversations (client_id);
create index idx_spark_conversations_expires on spark_conversations (expires_at);

-- =============================================================================
-- 4. spark_messages — Turn history
-- =============================================================================
create table if not exists spark_messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references spark_conversations(id) on delete cascade,
    role text not null,
    content text not null,
    created_at timestamptz not null default now()
);

create index idx_spark_messages_conversation on spark_messages (conversation_id, created_at);

-- =============================================================================
-- 5. spark_leads — Captured leads
-- =============================================================================
create table if not exists spark_leads (
    id uuid primary key default gen_random_uuid(),
    client_id uuid not null references spark_clients(id) on delete cascade,
    conversation_id uuid references spark_conversations(id) on delete set null,
    name text,
    email text,
    phone text,
    notes text,
    created_at timestamptz not null default now()
);

create index idx_spark_leads_client on spark_leads (client_id);

-- =============================================================================
-- 6. spark_events — Analytics tracking
-- =============================================================================
create table if not exists spark_events (
    id uuid primary key default gen_random_uuid(),
    client_id uuid not null references spark_clients(id) on delete cascade,
    conversation_id uuid references spark_conversations(id) on delete set null,
    event_type text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index idx_spark_events_client on spark_events (client_id, created_at);
create index idx_spark_events_type on spark_events (event_type);

-- =============================================================================
-- updated_at trigger — auto-update on row modification
-- =============================================================================
create or replace function spark_set_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

create trigger trg_spark_clients_updated_at
    before update on spark_clients
    for each row execute function spark_set_updated_at();

create trigger trg_spark_conversations_updated_at
    before update on spark_conversations
    for each row execute function spark_set_updated_at();

-- =============================================================================
-- RPC: match_spark_documents — Vector similarity search
-- =============================================================================
create or replace function match_spark_documents(
    p_client_id uuid,
    p_query_embedding vector(2000),
    p_match_count int default 5,
    p_threshold float default 0.3
)
returns table (
    id uuid,
    content text,
    title text,
    source_type text,
    source_url text,
    chunk_index int,
    similarity float
)
language plpgsql
security definer
as $$
begin
    return query
    select
        sd.id,
        sd.content,
        sd.title,
        sd.source_type,
        sd.source_url,
        sd.chunk_index,
        1 - (sd.embedding <=> p_query_embedding) as similarity
    from spark_documents sd
    where sd.client_id = p_client_id
      and sd.embedding is not null
      and 1 - (sd.embedding <=> p_query_embedding) > p_threshold
    order by sd.embedding <=> p_query_embedding
    limit p_match_count;
end;
$$;

-- =============================================================================
-- RLS Policies — Scope client admin access by auth.uid() -> user_id
-- =============================================================================
--
-- The backend uses a service_role key (bypasses RLS).
-- These policies protect the admin portal path where clients log in
-- via Supabase Auth to manage their own Spark instance.

-- Helper: get client IDs owned by the current auth user
create or replace function spark_my_client_ids()
returns setof uuid
language sql
security definer
stable
as $$
    select id from spark_clients where user_id = auth.uid();
$$;

-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
-- spark_clients
-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
alter table spark_clients enable row level security;

create policy "Clients: owner can read own row"
    on spark_clients for select
    using (user_id = auth.uid());

create policy "Clients: owner can update own row"
    on spark_clients for update
    using (user_id = auth.uid());

-- No INSERT/DELETE for clients — admin-only operations via service key

-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
-- spark_documents
-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
alter table spark_documents enable row level security;

create policy "Documents: owner can read own"
    on spark_documents for select
    using (client_id in (select spark_my_client_ids()));

create policy "Documents: owner can insert own"
    on spark_documents for insert
    with check (client_id in (select spark_my_client_ids()));

create policy "Documents: owner can delete own"
    on spark_documents for delete
    using (client_id in (select spark_my_client_ids()));

-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
-- spark_conversations
-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
alter table spark_conversations enable row level security;

create policy "Conversations: owner can read own"
    on spark_conversations for select
    using (client_id in (select spark_my_client_ids()));

-- No INSERT/UPDATE/DELETE — conversations are created/managed by the backend

-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
-- spark_messages
-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
alter table spark_messages enable row level security;

create policy "Messages: owner can read own"
    on spark_messages for select
    using (
        conversation_id in (
            select id from spark_conversations
            where client_id in (select spark_my_client_ids())
        )
    );

-- No INSERT/UPDATE/DELETE — messages are created by the backend

-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
-- spark_leads
-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
alter table spark_leads enable row level security;

create policy "Leads: owner can read own"
    on spark_leads for select
    using (client_id in (select spark_my_client_ids()));

-- No INSERT/UPDATE/DELETE — leads are created by the backend

-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
-- spark_events
-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
alter table spark_events enable row level security;

create policy "Events: owner can read own"
    on spark_events for select
    using (client_id in (select spark_my_client_ids()));

-- No INSERT/UPDATE/DELETE — events are created by the backend
