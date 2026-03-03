-- Migration 010: Profiles + Alignment Reports
-- Phase 3 of the Ingestion Pipeline
-- Adds tables for pipeline-generated profiles and alignment reports.

-- ═══════════════════════════════════════════════════════════════════════
-- SPARK PROFILES — Generated voice, values, boundaries, ICP, procedures
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS spark_profiles (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       uuid NOT NULL REFERENCES spark_clients(id) ON DELETE CASCADE,
    pipeline_run_id uuid NOT NULL REFERENCES spark_pipeline_runs(id) ON DELETE CASCADE,
    profile_type    text NOT NULL CHECK (profile_type IN ('voice', 'values', 'boundaries', 'icp', 'procedures')),
    version         int NOT NULL DEFAULT 1,
    content         text NOT NULL,
    status          text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'pending_review', 'approved', 'rejected')),
    client_feedback text,
    reviewed_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Auto-increment version per client+type
CREATE OR REPLACE FUNCTION spark_profiles_auto_version()
RETURNS TRIGGER AS $$
BEGIN
    SELECT COALESCE(MAX(version), 0) + 1
    INTO NEW.version
    FROM spark_profiles
    WHERE client_id = NEW.client_id AND profile_type = NEW.profile_type;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_spark_profiles_version
    BEFORE INSERT ON spark_profiles
    FOR EACH ROW
    EXECUTE FUNCTION spark_profiles_auto_version();

-- updated_at trigger
CREATE TRIGGER trg_spark_profiles_updated_at
    BEFORE UPDATE ON spark_profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Indices
CREATE INDEX IF NOT EXISTS idx_spark_profiles_client_type_version
    ON spark_profiles(client_id, profile_type, version DESC);

CREATE INDEX IF NOT EXISTS idx_spark_profiles_pipeline_run
    ON spark_profiles(pipeline_run_id);

-- RLS
ALTER TABLE spark_profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY spark_profiles_select ON spark_profiles
    FOR SELECT USING (client_id = auth.uid()::uuid);

CREATE POLICY spark_profiles_insert ON spark_profiles
    FOR INSERT WITH CHECK (client_id = auth.uid()::uuid);

CREATE POLICY spark_profiles_update ON spark_profiles
    FOR UPDATE USING (client_id = auth.uid()::uuid);


-- ═══════════════════════════════════════════════════════════════════════
-- SPARK ALIGNMENT REPORTS — Cross-reference contradiction analysis
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS spark_alignment_reports (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       uuid NOT NULL REFERENCES spark_clients(id) ON DELETE CASCADE,
    pipeline_run_id uuid NOT NULL REFERENCES spark_pipeline_runs(id) ON DELETE CASCADE,
    content         text NOT NULL,
    contradictions  jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Indices
CREATE INDEX IF NOT EXISTS idx_spark_alignment_reports_client
    ON spark_alignment_reports(client_id);

CREATE INDEX IF NOT EXISTS idx_spark_alignment_reports_pipeline_run
    ON spark_alignment_reports(pipeline_run_id);

-- RLS (internal access only — not exposed via client API)
ALTER TABLE spark_alignment_reports ENABLE ROW LEVEL SECURITY;

CREATE POLICY spark_alignment_reports_select ON spark_alignment_reports
    FOR SELECT USING (client_id = auth.uid()::uuid);

CREATE POLICY spark_alignment_reports_insert ON spark_alignment_reports
    FOR INSERT WITH CHECK (client_id = auth.uid()::uuid);
