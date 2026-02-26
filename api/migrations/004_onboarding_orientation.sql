-- ============================================================================
-- 004_onboarding_orientation.sql
-- Phase 1: Onboarding questionnaire storage + per-client orientation text.
--
-- onboarding_data: Structured JSONB for questionnaire responses (NOT embedded).
-- client_orientation: Full orientation text (replaces file-on-disk for production).
-- Knowledge category constraint extended for customer_profile and procedure.
-- ============================================================================

-- Add onboarding questionnaire responses (structured JSONB, not embedded)
ALTER TABLE spark_clients
ADD COLUMN IF NOT EXISTS onboarding_data JSONB DEFAULT '{}';

-- Add per-client orientation text (replaces file-on-disk for production)
-- NULL means: use template from settling_config.orientation_template (default: core.md)
ALTER TABLE spark_clients
ADD COLUMN IF NOT EXISTS client_orientation TEXT DEFAULT NULL;

-- Extend knowledge category constraint to include customer_profile and procedure
ALTER TABLE spark_knowledge_items
DROP CONSTRAINT IF EXISTS spark_knowledge_items_category_check;

ALTER TABLE spark_knowledge_items
ADD CONSTRAINT spark_knowledge_items_category_check
CHECK (category IN ('company', 'product', 'competitor', 'legal', 'team', 'fun', 'customer_profile', 'procedure'));
