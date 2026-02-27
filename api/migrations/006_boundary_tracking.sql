-- 006_boundary_tracking.sql
-- Add boundary signal tracking + CRM lead fields.

alter table spark_conversations
  add column if not exists boundary_signals_fired int not null default 0;

alter table spark_leads
  add column if not exists company_name text,
  add column if not exists crm_sync_status text not null default 'pending';

-- Atomic increment to avoid read-then-write race on concurrent requests.
create or replace function increment_boundary_signals(p_conversation_id uuid)
returns int as $$
  update spark_conversations
  set boundary_signals_fired = boundary_signals_fired + 1
  where id = p_conversation_id
  returning boundary_signals_fired;
$$ language sql;
