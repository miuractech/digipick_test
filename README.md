# Device Test Upload System

A Python script for uploading device test data and images to Supabase, with comprehensive SQL schema and batch processing capabilities.

## 🗄️ Database Schema

### Table Structure: `device_test`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key (auto-generated) |
| `created_at` | TIMESTAMP | Record creation time |
| `updated_at` | TIMESTAMP | Last update time (auto-updated) |
| `folder_name` | TEXT | Reference to source folder |
| `images` | TEXT[] | Array of uploaded image URLs |
| `device_id` | TEXT | Device identifier |
| `device_name` | TEXT | Human-readable device name |
| `device_type` | TEXT | Type/category of device |
| `data_type` | TEXT | Type of data being stored |
| `data` | JSONB | Main data payload from JSON files |
| `test_results` | JSONB | Flexible test data storage |
| `test_date` | TIMESTAMP | When the test was performed |
| `test_status` | TEXT | Status: pending/passed/failed/incomplete |
| `upload_batch` | TEXT | Batch identifier |
| `notes` | TEXT | Additional notes |
| `metadata` | JSONB | Additional flexible data |

## 🚀 Setup Instructions

### 1. Database Setup

Run the SQL schema in your Supabase SQL editor:

```bash
# Copy and paste the contents of schema.sql into Supabase SQL Editor
# Or use the Supabase CLI:
supabase db reset --linked
```

### 2. Python Environment

```bash
# Install dependencies
pip install -r requirements.txt

# Make script executable (Unix/Linux/Mac)
chmod +x script.py
```

### 3. Environment Configuration

Update the Supabase credentials in `script.py`:

```python
url: str = "YOUR_SUPABASE_URL"
key: str = "YOUR_SUPABASE_ANON_KEY"  # or service_role for scripts
```

## 📁 Folder Structure

The script expects this folder structure:

```
parent_folder/
├── subfolder1/
│   ├── data.json          # Single JSON file with device data
│   ├── image1.jpg         # Images (multiple allowed)
│   ├── image2.png
│   └── upload_success.json # Created after successful upload
├── subfolder2/
│   ├── device_data.json
│   ├── photo1.jpg
│   └── upload_failed.json  # Created if upload fails
```

## 🔧 Usage

### Basic Usage

```bash
# Process current directory subfolders
python script.py

# Process specific parent folder
python script.py /path/to/parent/folder
```

### JSON Data Format

Your data JSON files should contain device information:

```json
{
  "device_id": "DEV-001",
  "device_name": "Temperature Sensor A1",
  "device_type": "temperature_sensor",
  "test_date": "2024-01-15T10:30:00Z",
  "test_status": "passed",
  "test_results": {
    "temperature": {
      "value": 23.5,
      "unit": "celsius",
      "status": "normal"
    },
    "humidity": {
      "value": 45.2,
      "unit": "percent",
      "status": "normal"
    }
  },
  "metadata": {
    "batch": "2024-001",
    "technician": "John Doe"
  }
}
```

## 📊 Useful SQL Queries

### Get Upload Summary

```sql
SELECT * FROM get_device_test_summary();
```

### View Recent Uploads

```sql
SELECT 
    folder_name,
    device_id,
    device_name,
    test_status,
    array_length(images, 1) as image_count,
    created_at
FROM device_test
WHERE created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;
```

### Find Failed Tests

```sql
SELECT 
    folder_name,
    device_id,
    device_name,
    test_status,
    test_date
FROM device_test 
WHERE test_status = 'failed'
ORDER BY test_date DESC;
```

### Search Test Results

```sql
-- Find devices with temperature issues
SELECT 
    folder_name,
    device_id,
    test_results
FROM device_test
WHERE test_results @> '{"temperature": {"status": "out_of_range"}}';
```

### Get Devices with Most Images

```sql
SELECT 
    folder_name,
    device_id,
    device_name,
    array_length(images, 1) as image_count
FROM device_test
WHERE images IS NOT NULL
ORDER BY array_length(images, 1) DESC
LIMIT 10;
```

## 🔐 Security Features

### Row Level Security (RLS)
- Authenticated users can read/write data
- Service role has full access for scripts
- Public access denied by default

### Storage Policies
- Images stored in public `devicetest` bucket
- Organized by folder name: `devicetest/folder_name/image.jpg`
- Authenticated access required for uploads

## 🔄 Workflow

1. **Folder Scanning**: Script scans for subfolders, skips processed ones
2. **Sorting**: Processes folders by latest modification time first  
3. **JSON Upload**: Uploads device data to `device_test` table
4. **Image Upload**: Uploads images to `devicetest` storage bucket
5. **URL Update**: Updates database records with image URLs
6. **Result Logging**: Creates `upload_success.json` or `upload_failed.json`

## 📈 Performance Optimizations

- **Indexes**: Created on commonly queried fields
- **JSONB**: Efficient storage and querying of test results
- **Batch Processing**: Generator-based folder processing
- **Skip Logic**: Avoids reprocessing successful uploads

## 🐛 Error Handling

The script handles:
- Missing folders/files
- Invalid JSON format
- Network/upload failures  
- Multiple JSON files (expects only one)
- Image upload failures

## 📝 Logs and Results

### Success File (`upload_success.json`)
```json
{
  "timestamp": "2024-01-15T10:30:00.000000",
  "folder_name": "device_001",
  "json_upload": {
    "success": true,
    "filename": "data.json"
  },
  "image_upload": {
    "total_images": 3,
    "successful_uploads": 3,
    "uploaded_images": [...]
  },
  "summary": {
    "overall_success": true
  }
}
```

## 🔧 Customization

### Adding Custom Fields

Modify the table schema to add specific fields for your devices:

```sql
ALTER TABLE device_test ADD COLUMN serial_number TEXT;
ALTER TABLE device_test ADD COLUMN firmware_version TEXT;
CREATE INDEX idx_device_test_serial ON device_test(serial_number);
```

### Custom Test Status Values

Update the check constraint:

```sql
ALTER TABLE device_test DROP CONSTRAINT device_test_test_status_check;
ALTER TABLE device_test ADD CONSTRAINT device_test_test_status_check 
    CHECK (test_status IN ('pending', 'passed', 'failed', 'incomplete', 'reviewing', 'skipped'));
```

## 📞 Support

For issues or questions:
1. Check the generated `upload_failed.json` files for error details
2. Review Supabase logs for database/storage errors
3. Ensure proper permissions and bucket setup 