-- =============================================================================
-- 011: Create spark-uploads Storage Bucket
-- =============================================================================
-- The ingestion pipeline (008) created the spark_uploads table but never
-- created the actual Supabase Storage bucket.  This fixes "Bucket not found"
-- errors on file upload.
-- =============================================================================

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'spark-uploads',
    'spark-uploads',
    false,
    52428800,  -- 50 MB
    ARRAY[
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'text/plain',
        'text/markdown',
        'image/png',
        'image/jpeg',
        'image/webp'
    ]
)
ON CONFLICT (id) DO NOTHING;

-- ── Storage RLS ──────────────────────────────────────────────────────
-- The API uses the service_role key for uploads (presign → upload → confirm),
-- so these policies only need to allow the service role.  Client-side reads
-- are not needed — parsed text is served from the spark_uploads table.

CREATE POLICY "service_role_all" ON storage.objects
    FOR ALL
    USING (bucket_id = 'spark-uploads')
    WITH CHECK (bucket_id = 'spark-uploads');
