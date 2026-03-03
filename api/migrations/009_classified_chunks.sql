-- =============================================================================
-- 009: Classified Chunks + Website URL
-- =============================================================================
-- Stage 1 classification output table and website_url on spark_clients.
-- =============================================================================

-- ── website_url on spark_clients ───────────────────────────────────
-- First-class column, not buried in settling_config.

ALTER TABLE spark_clients ADD COLUMN IF NOT EXISTS website_url text;

-- ── spark_classified_chunks ────────────────────────────────────────
-- Stage 1 output: each source chunk classified with signal types.
-- No embedding column — deferred until a retrieval consumer exists.

CREATE TABLE IF NOT EXISTS spark_classified_chunks (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_run_id uuid NOT NULL REFERENCES spark_pipeline_runs(id) ON DELETE CASCADE,
    client_id       uuid NOT NULL REFERENCES spark_clients(id) ON DELETE CASCADE,
    source_type     text NOT NULL
                        CHECK (source_type IN ('upload', 'paste', 'questionnaire', 'scrape')),
    source_id       uuid,
    content         text NOT NULL,
    signal_types    text[] NOT NULL DEFAULT '{}',
    confidence      float NOT NULL DEFAULT 0.0,
    metadata        jsonb DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_spark_classified_chunks_run_id
    ON spark_classified_chunks(pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_spark_classified_chunks_client_id
    ON spark_classified_chunks(client_id);
CREATE INDEX IF NOT EXISTS idx_spark_classified_chunks_signal_types
    ON spark_classified_chunks USING GIN(signal_types);

ALTER TABLE spark_classified_chunks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "classified_chunks_select_own" ON spark_classified_chunks
    FOR SELECT USING (client_id = auth.uid()::uuid);
