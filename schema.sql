-- ============================================================================
-- SUPABASE SCHEMA AND SETUP FOR DEVICE TEST UPLOAD SYSTEM
-- ============================================================================

-- ============================================================================
-- 1. CREATE DEVICE_TEST TABLE
-- ============================================================================

-- Drop table if exists (for development - remove in production)
-- DROP TABLE IF EXISTS device_test CASCADE;

-- Create the main device_test table
CREATE TABLE IF NOT EXISTS device_test (
    -- Primary key
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Folder reference (from upload script)
    folder_name TEXT NOT NULL,
    
    -- Image URLs array (populated after image upload)
    images TEXT[] DEFAULT '{}',
    
    -- Device/Test data (JSON structure - customize based on your needs)
    device_id TEXT,
    device_name TEXT,
    device_type TEXT,
    data_type TEXT,
    data JSONB,
    test_results JSONB,
    test_date TIMESTAMP WITH TIME ZONE,
    test_status TEXT CHECK (test_status IN ('pending', 'passed', 'failed', 'incomplete')),
    
    -- Metadata
    upload_batch TEXT,
    notes TEXT,
    
    -- Additional flexible data storage
    metadata JSONB DEFAULT '{}',
    
    -- Indexes for performance
    CONSTRAINT unique_folder_device UNIQUE(folder_name, device_id)
);

-- ============================================================================
-- 2. CREATE INDEXES FOR PERFORMANCE
-- ============================================================================

-- Index on folder_name for quick lookups
CREATE INDEX IF NOT EXISTS idx_device_test_folder_name ON device_test(folder_name);

-- Index on device_id for device queries
CREATE INDEX IF NOT EXISTS idx_device_test_device_id ON device_test(device_id);

-- Index on test_date for time-based queries
CREATE INDEX IF NOT EXISTS idx_device_test_test_date ON device_test(test_date);

-- Index on test_status for status filtering
CREATE INDEX IF NOT EXISTS idx_device_test_status ON device_test(test_status);

-- Index on data_type for data type filtering
CREATE INDEX IF NOT EXISTS idx_device_test_data_type ON device_test(data_type);

-- GIN index for JSONB metadata queries
CREATE INDEX IF NOT EXISTS idx_device_test_metadata ON device_test USING GIN(metadata);

-- GIN index for test_results JSONB
CREATE INDEX IF NOT EXISTS idx_device_test_results ON device_test USING GIN(test_results);

-- GIN index for data JSONB
CREATE INDEX IF NOT EXISTS idx_device_test_data ON device_test USING GIN(data);

-- ============================================================================
-- 3. CREATE UPDATED_AT TRIGGER
-- ============================================================================

-- Function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger to automatically update updated_at
DROP TRIGGER IF EXISTS update_device_test_updated_at ON device_test;
CREATE TRIGGER update_device_test_updated_at
    BEFORE UPDATE ON device_test
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- 4. ROW LEVEL SECURITY (RLS) POLICIES
-- ============================================================================

-- Enable RLS on the table
ALTER TABLE device_test ENABLE ROW LEVEL SECURITY;

-- Policy for authenticated users to read all records
CREATE POLICY "Users can view all device tests" ON device_test
    FOR SELECT USING (auth.role() = 'authenticated');

-- Policy for authenticated users to insert records
CREATE POLICY "Users can insert device tests" ON device_test
    FOR INSERT WITH CHECK (auth.role() = 'authenticated');

-- Policy for authenticated users to update records
CREATE POLICY "Users can update device tests" ON device_test
    FOR UPDATE USING (auth.role() = 'authenticated');

-- Policy for service role to have full access (for scripts)
CREATE POLICY "Service role full access" ON device_test
    FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

-- ============================================================================
-- 5. STORAGE BUCKET SETUP
-- ============================================================================

-- Create storage bucket for device test images
INSERT INTO storage.buckets (id, name, public)
VALUES ('devicetest', 'devicetest', true)
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- 6. STORAGE POLICIES
-- ============================================================================

-- Policy for authenticated users to view images
CREATE POLICY "Users can view device test images" ON storage.objects
    FOR SELECT USING (bucket_id = 'devicetest' AND auth.role() = 'authenticated');

-- Policy for authenticated users to upload images
CREATE POLICY "Users can upload device test images" ON storage.objects
    FOR INSERT WITH CHECK (
        bucket_id = 'devicetest' 
        AND auth.role() = 'authenticated'
        AND (storage.foldername(name))[1] IS NOT NULL  -- Ensure folder structure
    );

-- Policy for service role to have full access to storage
CREATE POLICY "Service role storage access" ON storage.objects
    FOR ALL USING (
        bucket_id = 'devicetest' 
        AND auth.jwt() ->> 'role' = 'service_role'
    );

-- ============================================================================
-- 7. HELPER FUNCTIONS
-- ============================================================================

-- Function to get device test summary
CREATE OR REPLACE FUNCTION get_device_test_summary()
RETURNS TABLE (
    total_tests BIGINT,
    passed_tests BIGINT,
    failed_tests BIGINT,
    pending_tests BIGINT,
    latest_test_date TIMESTAMP WITH TIME ZONE
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        COUNT(*) as total_tests,
        COUNT(*) FILTER (WHERE test_status = 'passed') as passed_tests,
        COUNT(*) FILTER (WHERE test_status = 'failed') as failed_tests,
        COUNT(*) FILTER (WHERE test_status = 'pending') as pending_tests,
        MAX(test_date) as latest_test_date
    FROM device_test;
END;
$$ LANGUAGE plpgsql;

-- Function to get tests by folder
CREATE OR REPLACE FUNCTION get_tests_by_folder(folder_name_param TEXT)
RETURNS SETOF device_test AS $$
BEGIN
    RETURN QUERY
    SELECT * FROM device_test 
    WHERE folder_name = folder_name_param
    ORDER BY created_at DESC;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 8. EXAMPLE QUERIES
-- ============================================================================

/*
-- Get all device tests with their images
SELECT 
    id,
    folder_name,
    device_id,
    device_name,
    test_status,
    array_length(images, 1) as image_count,
    images,
    created_at
FROM device_test
ORDER BY created_at DESC;

-- Get test summary
SELECT * FROM get_device_test_summary();

-- Get tests for a specific folder
SELECT * FROM get_tests_by_folder('sample_folder');

-- Get tests with failed status
SELECT 
    folder_name,
    device_id,
    device_name,
    test_status,
    test_date
FROM device_test 
WHERE test_status = 'failed'
ORDER BY test_date DESC;

-- Get devices with most images
SELECT 
    folder_name,
    device_id,
    device_name,
    array_length(images, 1) as image_count
FROM device_test
WHERE images IS NOT NULL
ORDER BY array_length(images, 1) DESC;

-- Search in test results JSON
SELECT 
    folder_name,
    device_id,
    test_results
FROM device_test
WHERE test_results @> '{"temperature": {"status": "normal"}}';

-- Get recent uploads (last 24 hours)
SELECT 
    folder_name,
    device_id,
    created_at
FROM device_test
WHERE created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;
*/

-- ============================================================================
-- 9. SAMPLE DATA (OPTIONAL - FOR TESTING)
-- ============================================================================

/*
-- Insert sample data for testing
INSERT INTO device_test (
    folder_name,
    device_id,
    device_name,
    device_type,
    test_status,
    test_date,
    test_results,
    metadata
) VALUES 
(
    'sample_device_001',
    'DEV-001',
    'Temperature Sensor A1',
    'temperature_sensor',
    'passed',
    NOW() - INTERVAL '1 hour',
    '{"temperature": {"value": 23.5, "unit": "celsius", "status": "normal"}, "humidity": {"value": 45.2, "unit": "percent", "status": "normal"}}',
    '{"batch": "2024-001", "technician": "John Doe"}'
),
(
    'sample_device_002',
    'DEV-002',
    'Pressure Sensor B2',
    'pressure_sensor',
    'failed',
    NOW() - INTERVAL '2 hours',
    '{"pressure": {"value": 1025.3, "unit": "hPa", "status": "out_of_range"}, "calibration": {"status": "failed"}}',
    '{"batch": "2024-001", "technician": "Jane Smith"}'
);
*/ 