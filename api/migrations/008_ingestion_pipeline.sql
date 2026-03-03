-- =============================================================================
-- 008: Ingestion Pipeline — Uploads, Paste Items, Pipeline Runs
-- =============================================================================
-- Supports the multi-source ingestion pipeline: file upload tracking,
-- ad-hoc pasted text, and async pipeline job orchestration.
-- =============================================================================

-- ── spark_uploads ──────────────────────────────────────────────────
-- Tracks uploaded files (and scraped pages in Phase 2).

CREATE TABLE IF NOT EXISTS spark_uploads (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       uuid NOT NULL REFERENCES spark_clients(id) ON DELETE CASCADE,
    filename        text NOT NULL,
    original_name   text NOT NULL,
    mime_type       text NOT NULL,
    file_size       bigint NOT NULL,
    storage_path    text NOT NULL,
    source_type     text NOT NULL DEFAULT 'upload'
                        CHECK (source_type IN ('upload', 'scrape')),
    status          text NOT NULL DEFAULT 'uploaded'
                        CHECK (status IN ('uploaded', 'parsing', 'parsed', 'failed')),
    parsed_text     text,
    page_count      int,
    error_message   text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_spark_uploads_client_id
    ON spark_uploads(client_id);
CREATE INDEX IF NOT EXISTS idx_spark_uploads_client_status
    ON spark_uploads(client_id, status);

ALTER TABLE spark_uploads ENABLE ROW LEVEL SECURITY;

CREATE POLICY "uploads_select_own" ON spark_uploads
    FOR SELECT USING (client_id = auth.uid()::uuid);
CREATE POLICY "uploads_insert_own" ON spark_uploads
    FOR INSERT WITH CHECK (client_id = auth.uid()::uuid);
CREATE POLICY "uploads_delete_own" ON spark_uploads
    FOR DELETE USING (client_id = auth.uid()::uuid);

-- ── spark_paste_items ──────────────────────────────────────────────
-- Ad-hoc pasted text submitted by clients during ingestion.

CREATE TABLE IF NOT EXISTS spark_paste_items (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id   uuid NOT NULL REFERENCES spark_clients(id) ON DELETE CASCADE,
    content     text NOT NULL,
    title       text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_spark_paste_items_client_id
    ON spark_paste_items(client_id);

ALTER TABLE spark_paste_items ENABLE ROW LEVEL SECURITY;

CREATE POLICY "paste_items_select_own" ON spark_paste_items
    FOR SELECT USING (client_id = auth.uid()::uuid);
CREATE POLICY "paste_items_insert_own" ON spark_paste_items
    FOR INSERT WITH CHECK (client_id = auth.uid()::uuid);
CREATE POLICY "paste_items_delete_own" ON spark_paste_items
    FOR DELETE USING (client_id = auth.uid()::uuid);

-- ── spark_pipeline_runs ────────────────────────────────────────────
-- Async pipeline job tracking with heartbeat for crash detection.

CREATE TABLE IF NOT EXISTS spark_pipeline_runs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       uuid NOT NULL REFERENCES spark_clients(id) ON DELETE CASCADE,
    status          text NOT NULL DEFAULT 'pending'
                        CHECK (status IN (
                            'pending', 'stage_0_scrape', 'stage_1',
                            'stage_2', 'stage_3', 'completed',
                            'failed', 'cancelled'
                        )),
    trigger_type    text NOT NULL DEFAULT 'manual'
                        CHECK (trigger_type IN ('manual', 'auto', 'rerun')),
    progress        jsonb DEFAULT '{"stage": null, "percent": 0, "message": "Queued"}'::jsonb,
    source_summary  jsonb DEFAULT '{}'::jsonb,
    error_message   text,
    cancelled       boolean NOT NULL DEFAULT false,
    last_heartbeat  timestamptz,
    started_at      timestamptz,
    completed_at    timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_spark_pipeline_runs_client_id
    ON spark_pipeline_runs(client_id);
CREATE INDEX IF NOT EXISTS idx_spark_pipeline_runs_client_status
    ON spark_pipeline_runs(client_id, status);

ALTER TABLE spark_pipeline_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "pipeline_runs_select_own" ON spark_pipeline_runs
    FOR SELECT USING (client_id = auth.uid()::uuid);

-- ── updated_at trigger ─────────────────────────────────────────────

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_spark_uploads_updated_at
    BEFORE UPDATE ON spark_uploads
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_spark_pipeline_runs_updated_at
    BEFORE UPDATE ON spark_pipeline_runs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
