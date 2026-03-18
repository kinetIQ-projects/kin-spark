-- 012: Add source column to spark_leads for conversational vs form-based capture
alter table spark_leads
  add column if not exists source text not null default 'form';
