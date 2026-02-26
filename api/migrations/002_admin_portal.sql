-- =============================================================================
-- Kin Spark — Admin Portal Migration (002)
-- Run via Supabase SQL Editor after 001 (spark_schema.sql)
-- =============================================================================

-- =============================================================================
-- 1. spark_sources — Knowledge source tracking
-- =============================================================================
create table if not exists spark_sources (
    id uuid primary key default gen_random_uuid(),
    client_id uuid not null references spark_clients(id) on delete cascade,
    title text not null,
    source_type text not null default 'text',
    source_url text,
    chunk_count int not null default 0,
    status text not null default 'active',
    error_message text,
    ingested_at timestamptz not null default now(),
    created_at timestamptz not null default now()
);

create index idx_spark_sources_client on spark_sources (client_id);

-- RLS
alter table spark_sources enable row level security;

create policy "Sources: owner can read own"
    on spark_sources for select
    using (client_id in (select spark_my_client_ids()));

create policy "Sources: owner can insert own"
    on spark_sources for insert
    with check (client_id in (select spark_my_client_ids()));

create policy "Sources: owner can delete own"
    on spark_sources for delete
    using (client_id in (select spark_my_client_ids()));

-- =============================================================================
-- 2. Alter spark_documents — add source_id FK
-- =============================================================================
alter table spark_documents
    add column if not exists source_id uuid references spark_sources(id) on delete set null;

-- =============================================================================
-- 3. Alter spark_conversations — admin portal fields
-- =============================================================================
alter table spark_conversations
    add column if not exists sentiment text,
    add column if not exists sentiment_score float,
    add column if not exists summary text,
    add column if not exists outcome text,
    add column if not exists ended_at timestamptz;

-- Index for filtering by outcome
create index idx_spark_conversations_outcome on spark_conversations (client_id, outcome);

-- =============================================================================
-- 4. Alter spark_leads — status tracking + admin notes
-- =============================================================================
alter table spark_leads
    add column if not exists status text not null default 'new',
    add column if not exists admin_notes text;

-- Index for filtering by status
create index idx_spark_leads_status on spark_leads (client_id, status);

-- RLS: allow owner to update own leads (for status + notes changes)
create policy "Leads: owner can update own"
    on spark_leads for update
    using (client_id in (select spark_my_client_ids()));

-- =============================================================================
-- 5. Alter spark_clients — widget, messaging, integration, limit columns
-- =============================================================================

-- Widget appearance
alter table spark_clients
    add column if not exists accent_color text default '#6366f1',
    add column if not exists widget_position text default 'bottom-right',
    add column if not exists widget_title text,
    add column if not exists widget_avatar_url text;

-- Messaging
alter table spark_clients
    add column if not exists greeting_message text,
    add column if not exists wind_down_message text,
    add column if not exists dont_know_response text,
    add column if not exists offline_message text,
    add column if not exists off_limits_topics jsonb default '[]'::jsonb;

-- Integration
alter table spark_clients
    add column if not exists escalation_email text,
    add column if not exists hubspot_api_key_encrypted text,
    add column if not exists calendly_link text,
    add column if not exists webhook_url text,
    add column if not exists slack_webhook_url text;

-- Notifications
alter table spark_clients
    add column if not exists notification_email text,
    add column if not exists notifications_enabled boolean not null default false;

-- Limits
alter table spark_clients
    add column if not exists daily_conversation_cap int,
    add column if not exists sessions_per_visitor_per_day int;
