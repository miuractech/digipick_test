-- ============================================================================
-- MIGRATION SCRIPT FOR DEVICE_TEST TABLE
-- Run this if you already have a device_test table without data_type and data columns
-- ============================================================================

-- Add missing columns to existing table
ALTER TABLE device_test 
ADD COLUMN IF NOT EXISTS data_type TEXT,
ADD COLUMN IF NOT EXISTS data JSONB;

-- Create indexes for the new columns
CREATE INDEX IF NOT EXISTS idx_device_test_data_type ON device_test(data_type);
CREATE INDEX IF NOT EXISTS idx_device_test_data ON device_test USING GIN(data);

-- Migrate existing data (if any) to populate the new columns
-- This assumes existing records have some structure we can work with
UPDATE device_test 
SET 
    data_type = COALESCE(data_type, 'device_test'),
    data = CASE 
        WHEN data IS NULL THEN 
            jsonb_build_object(
                'device_id', device_id,
                'device_name', device_name,
                'device_type', device_type,
                'test_results', test_results,
                'test_date', test_date,
                'test_status', test_status,
                'upload_batch', upload_batch,
                'notes', notes,
                'metadata', metadata
            )
        ELSE data 
    END
WHERE data_type IS NULL OR data IS NULL;

-- Verify the migration
SELECT 
    COUNT(*) as total_records,
    COUNT(data_type) as records_with_data_type,
    COUNT(data) as records_with_data
FROM device_test; 