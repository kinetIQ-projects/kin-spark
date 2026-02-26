-- ============================================================================
-- 003_knowledge_items.sql
-- Admin-managed knowledge items with category, priority, and vector search.
--
-- Separate from spark_documents (auto-chunked URL ingestion). Knowledge items
-- are curated single entries — no chunking, max 3000 chars, with category and
-- priority for admin management.
--
-- HNSW index: negligible overhead at small scale, ready for growth.
-- ============================================================================

-- Table
CREATE TABLE IF NOT EXISTS spark_knowledge_items (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       uuid NOT NULL REFERENCES spark_clients(id) ON DELETE CASCADE,
    title           text NOT NULL,
    content         text NOT NULL,
    category        text NOT NULL DEFAULT 'company'
                    CHECK (category IN ('company', 'product', 'competitor', 'legal', 'team', 'fun')),
    subcategory     text,
    priority        int NOT NULL DEFAULT 0,
    active          boolean NOT NULL DEFAULT true,
    embedding       vector(2000),
    embedding_model text,
    content_hash    text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Unique constraint: one content hash per client
ALTER TABLE spark_knowledge_items
    ADD CONSTRAINT uq_knowledge_client_hash UNIQUE (client_id, content_hash);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_knowledge_client
    ON spark_knowledge_items (client_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_client_category
    ON spark_knowledge_items (client_id, category);
CREATE INDEX IF NOT EXISTS idx_knowledge_client_active
    ON spark_knowledge_items (client_id, active);

-- HNSW vector index for similarity search
CREATE INDEX IF NOT EXISTS idx_knowledge_embedding_hnsw
    ON spark_knowledge_items
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- updated_at trigger (reuse existing function from spark_documents migration)
CREATE TRIGGER set_knowledge_updated_at
    BEFORE UPDATE ON spark_knowledge_items
    FOR EACH ROW
    EXECUTE FUNCTION spark_set_updated_at();

-- ============================================================================
-- RLS Policies
-- ============================================================================

ALTER TABLE spark_knowledge_items ENABLE ROW LEVEL SECURITY;

-- Service role bypasses RLS. These policies are for direct client access.
CREATE POLICY "knowledge_select_own"
    ON spark_knowledge_items FOR SELECT
    USING (client_id IN (SELECT spark_my_client_ids()));

CREATE POLICY "knowledge_insert_own"
    ON spark_knowledge_items FOR INSERT
    WITH CHECK (client_id IN (SELECT spark_my_client_ids()));

CREATE POLICY "knowledge_update_own"
    ON spark_knowledge_items FOR UPDATE
    USING (client_id IN (SELECT spark_my_client_ids()));

CREATE POLICY "knowledge_delete_own"
    ON spark_knowledge_items FOR DELETE
    USING (client_id IN (SELECT spark_my_client_ids()));

-- ============================================================================
-- RPC: Vector similarity search for active knowledge items
-- ============================================================================

CREATE OR REPLACE FUNCTION match_spark_knowledge(
    p_client_id     uuid,
    p_query_embedding vector(2000),
    p_match_count   int DEFAULT 5,
    p_threshold     float DEFAULT 0.3
)
RETURNS TABLE (
    id          uuid,
    content     text,
    title       text,
    category    text,
    subcategory text,
    priority    int,
    similarity  float
)
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    RETURN QUERY
    SELECT
        ki.id,
        ki.content,
        ki.title,
        ki.category,
        ki.subcategory,
        ki.priority,
        1 - (ki.embedding <=> p_query_embedding) AS similarity
    FROM spark_knowledge_items ki
    WHERE ki.client_id = p_client_id
      AND ki.active = true
      AND ki.embedding IS NOT NULL
      AND 1 - (ki.embedding <=> p_query_embedding) > p_threshold
    ORDER BY ki.embedding <=> p_query_embedding
    LIMIT p_match_count;
END;
$$;
