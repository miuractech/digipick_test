#!/usr/bin/env python3
"""
Supabase Upload Script
Processes subfolders and uploads JSON files to device_test table and images to device_test bucket in Supabase
"""

import json
import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from supabase import create_client, Client
from supabase.lib.client_options import ClientOptions

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('upload_log.txt'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class UploadError(Exception):
    """Custom exception for upload-related errors"""
    pass

class ValidationError(Exception):
    """Custom exception for data validation errors"""
    pass

def validate_environment() -> None:
    """Validate environment and dependencies"""
    try:
        # Check if required modules are available
        import supabase
        logger.info("✓ Supabase client library available")
    except ImportError as e:
        error_msg = f"Missing required dependency: {e}"
        print(f"ERROR: {error_msg}")
        raise UploadError(error_msg)

def validate_supabase_connection(supabase: Client) -> bool:
    """Validate Supabase connection"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Test connection by making a simple query
            response = supabase.table("device_test").select("count", count="exact").limit(1).execute()
            logger.info("✓ Supabase connection validated")
            return True
        except Exception as e:
            error_msg = f"Connection attempt {attempt + 1}/{max_retries} failed: {e}"
            logger.warning(error_msg)
            print(f"WARNING: {error_msg}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                final_error = "Failed to establish Supabase connection after all retries"
                logger.error(final_error)
                print(f"ERROR: {final_error}")
                return False
    return False

def validate_json_structure(data: Any, filename: str) -> None:
    """Validate JSON data structure"""
    if not isinstance(data, (dict, list)):
        raise ValidationError(f"Invalid JSON structure in {filename}: must be dict or list")
    
    if isinstance(data, list):
        if not data:
            raise ValidationError(f"Empty JSON array in {filename}")
        if not all(isinstance(item, dict) for item in data):
            raise ValidationError(f"Invalid JSON array in {filename}: all items must be objects")
    
    # Validate required fields for device_test records
    records = [data] if isinstance(data, dict) else data
    for i, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        
        # Check for at least one identifier
        identifiers = ['device_id', 'device_name', 'data_type']
        if not any(record.get(field) for field in identifiers):
            logger.warning(f"Record {i} in {filename} lacks identifying fields: {identifiers}")

def get_subfolders_to_process(parent_folder: str) -> List[Tuple[str, str]]:
    """Get subfolders to process with comprehensive error handling"""
    try:
        if not os.path.exists(parent_folder):
            raise UploadError(f"Parent folder '{parent_folder}' not found")
        
        if not os.path.isdir(parent_folder):
            raise UploadError(f"'{parent_folder}' is not a directory")
        
        if not os.access(parent_folder, os.R_OK):
            raise UploadError(f"No read permission for '{parent_folder}'")
        
        # Get all subdirectories
        subfolders = []
        
        try:
            items = os.listdir(parent_folder)
        except PermissionError:
            raise UploadError(f"Permission denied accessing '{parent_folder}'")
        except OSError as e:
            raise UploadError(f"OS error accessing '{parent_folder}': {e}")
        
        for item in items:
            try:
                item_path = os.path.join(parent_folder, item)
                if not os.path.isdir(item_path):
                    continue
                
                # Check if already processed (has upload_success.json)
                success_file = os.path.join(item_path, "upload_success.json")
                if os.path.exists(success_file):
                    logger.info(f"⏭️  Skipping {item} - already processed (upload_success.json found)")
                    continue
                
                # Get modification time with error handling
                try:
                    mod_time = os.path.getmtime(item_path)
                    subfolders.append((item_path, mod_time, item))
                except OSError as e:
                    logger.warning(f"Could not get modification time for {item}: {e}")
                    # Use current time as fallback
                    subfolders.append((item_path, time.time(), item))
                    
            except Exception as e:
                logger.warning(f"Error processing item '{item}': {e}")
                continue
        
        # Sort by modification time (latest first)
        subfolders.sort(key=lambda x: x[1], reverse=True)
        
        logger.info(f"Found {len(subfolders)} subfolder(s) to process (sorted by latest first)")
        
        return [(folder_path, folder_name) for folder_path, _, folder_name in subfolders]
        
    except UploadError:
        raise
    except Exception as e:
        error_msg = f"Unexpected error getting subfolders: {e}"
        print(f"ERROR: {error_msg}")
        raise UploadError(error_msg)

def get_image_files(folder_path: str) -> List[str]:
    """Get all image files from the folder with error handling"""
    try:
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}
        image_files = []
        
        if not os.access(folder_path, os.R_OK):
            logger.warning(f"No read permission for folder: {folder_path}")
            return []
        
        try:
            files = os.listdir(folder_path)
        except PermissionError:
            error_msg = f"Permission denied accessing folder: {folder_path}"
            logger.error(error_msg)
            print(f"ERROR: {error_msg}")
            return []
        except OSError as e:
            error_msg = f"OS error accessing folder {folder_path}: {e}"
            logger.error(error_msg)
            print(f"ERROR: {error_msg}")
            return []
        
        for filename in files:
            try:
                file_path = os.path.join(folder_path, filename)
                if os.path.isfile(file_path) and Path(filename).suffix.lower() in image_extensions:
                    # Validate file is readable and not corrupted
                    if os.access(file_path, os.R_OK) and os.path.getsize(file_path) > 0:
                        image_files.append(filename)
                    else:
                        logger.warning(f"Skipping unreadable or empty image: {filename}")
            except Exception as e:
                logger.warning(f"Error processing image file {filename}: {e}")
                continue
        
        return image_files
        
    except Exception as e:
        error_msg = f"Unexpected error getting image files from {folder_path}: {e}"
        logger.error(error_msg)
        print(f"ERROR: {error_msg}")
        return []

def upload_image_with_retry(supabase: Client, file_path: str, storage_path: str, 
                          bucket_name: str, max_retries: int = 3) -> Tuple[bool, str, str]:
    """Upload a single image with retry logic"""
    for attempt in range(max_retries):
        try:
            # Validate file exists and is readable
            if not os.path.exists(file_path):
                return False, f"File not found: {file_path}", ""
            
            if not os.access(file_path, os.R_OK):
                return False, f"No read permission for file: {file_path}", ""
            
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                return False, f"File is empty: {file_path}", ""
            
            if file_size > 50 * 1024 * 1024:  # 50MB limit
                return False, f"File too large ({file_size} bytes): {file_path}", ""
            
            # Read file with error handling
            try:
                with open(file_path, 'rb') as f:
                    file_data = f.read()
            except IOError as e:
                return False, f"Error reading file {file_path}: {e}", ""
            
            # Determine content type
            extension = Path(file_path).suffix[1:].lower()
            content_type = f"image/{extension}"
            if extension == 'jpg':
                content_type = "image/jpeg"
            
            # Upload to bucket with timeout
            response = supabase.storage.from_(bucket_name).upload(
                path=storage_path,
                file=file_data,
                file_options={"content-type": content_type}
            )
            
            # Get public URL
            public_url = supabase.storage.from_(bucket_name).get_public_url(storage_path)
            
            if not public_url:
                return False, "Failed to get public URL", ""
            
            return True, "", public_url
            
        except Exception as e:
            error_msg = f"Upload attempt {attempt + 1}/{max_retries} failed: {e}"
            logger.warning(error_msg)
            
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                return False, f"All upload attempts failed. Last error: {e}", ""
    
    return False, "Max retries exceeded", ""

def upload_images_to_bucket(supabase: Client, folder_path: str, folder_name: str, 
                          image_files: List[str]) -> Tuple[List[Dict], List[Dict], List[str]]:
    """Upload images to Supabase storage bucket with comprehensive error handling"""
    bucket_name = "devicetest"
    uploaded_images = []
    failed_images = []
    image_urls = []
    
    if not image_files:
        logger.info("No image files to upload")
        return uploaded_images, failed_images, image_urls
    
    logger.info(f"Uploading {len(image_files)} images to bucket '{bucket_name}'")
    
    for i, image_file in enumerate(image_files, 1):
        try:
            logger.info(f"Uploading image {i}/{len(image_files)}: {image_file}")
            
            file_path = os.path.join(folder_path, image_file)
            storage_path = f"{folder_name}/{image_file}"
            
            success, error_msg, public_url = upload_image_with_retry(
                supabase, file_path, storage_path, bucket_name
            )
            
            if success:
                file_size = os.path.getsize(file_path)
                uploaded_images.append({
                    "filename": image_file,
                    "storage_path": storage_path,
                    "public_url": public_url,
                    "size_bytes": file_size
                })
                image_urls.append(public_url)
                logger.info(f"    ✓ Uploaded: {image_file} -> {public_url}")
            else:
                failed_images.append({
                    "filename": image_file,
                    "error": error_msg
                })
                logger.error(f"    ✗ Failed: {image_file} - {error_msg}")
            
        except Exception as e:
            error_msg = f"Unexpected error uploading {image_file}: {e}"
            failed_images.append({
                "filename": image_file,
                "error": error_msg
            })
            logger.error(f"    ✗ {error_msg}")
            print(f"ERROR: {error_msg}")
    
    success_count = len(uploaded_images)
    total_count = len(image_files)
    logger.info(f"Image upload summary: {success_count}/{total_count} successful")
    
    return uploaded_images, failed_images, image_urls

def insert_data_with_retry(supabase: Client, table_name: str, records: List[Dict], 
                         max_retries: int = 3) -> Tuple[bool, str, int]:
    """Insert data to database with retry logic"""
    for attempt in range(max_retries):
        try:
            response = supabase.table(table_name).insert(records).execute()
            
            if hasattr(response, 'data') and response.data:
                return True, "", len(response.data)
            else:
                return False, "No data returned from insert operation", 0
                
        except Exception as e:
            error_msg = f"Database insert attempt {attempt + 1}/{max_retries} failed: {e}"
            logger.warning(error_msg)
            
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.info(f"Retrying database insert in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                return False, f"All database insert attempts failed. Last error: {e}", 0
    
    return False, "Max retries exceeded", 0

def write_result_file(folder_path: str, filename: str, data: Dict) -> bool:
    """Write result data to JSON file with error handling"""
    try:
        if not os.access(folder_path, os.W_OK):
            logger.error(f"No write permission for folder: {folder_path}")
            return False
        
        result_file_path = os.path.join(folder_path, filename)
        
        # Create backup if file exists
        if os.path.exists(result_file_path):
            backup_path = f"{result_file_path}.backup"
            try:
                os.rename(result_file_path, backup_path)
                logger.info(f"Created backup: {backup_path}")
            except OSError as e:
                logger.warning(f"Could not create backup: {e}")
        
        # Write new file
        with open(result_file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        # Validate written file
        try:
            with open(result_file_path, 'r', encoding='utf-8') as f:
                json.load(f)
            logger.info(f"    ✓ Result file written and validated: {result_file_path}")
            return True
        except json.JSONDecodeError:
            logger.error(f"Written file is not valid JSON: {result_file_path}")
            return False
            
    except Exception as e:
        error_msg = f"Failed to write result file {filename}: {e}"
        logger.error(f"    ✗ {error_msg}")
        print(f"ERROR: {error_msg}")
        return False

def process_single_folder(supabase: Client, folder_path: str, folder_name: str, 
                         table_name: str) -> bool:
    """Process a single folder with comprehensive error handling"""
    logger.info(f"\n📁 Processing folder: {folder_name}")
    
    try:
        # Validate folder access
        if not os.path.exists(folder_path):
            raise UploadError(f"Folder not found: {folder_path}")
        
        if not os.access(folder_path, os.R_OK):
            raise UploadError(f"No read permission for folder: {folder_path}")
        
        # Get files (exclude result files from previous runs)
        excluded_json_files = {'upload_success.json', 'upload_failed.json'}
        
        try:
            all_files = os.listdir(folder_path)
        except OSError as e:
            raise UploadError(f"Cannot read folder contents: {e}")
        
        json_files = [f for f in all_files 
                      if f.endswith('.json') and f not in excluded_json_files]
        image_files = get_image_files(folder_path)
        
        logger.info(f"    Found {len(json_files)} JSON file(s) and {len(image_files)} image(s)")
        
        # Metadata for result files
        timestamp = datetime.now().isoformat()
        metadata = {
            "timestamp": timestamp,
            "folder_name": folder_name,
            "folder_path": folder_path,
            "table_name": table_name,
            "bucket_name": "devicetest"
        }
        
        # Process JSON file
        json_upload_success = False
        json_data = None
        json_error = None
        records_inserted = 0
        
        if len(json_files) == 0:
            json_error = "No JSON files found in folder"
            logger.warning(f"    ⚠️  {json_error}")
        elif len(json_files) > 1:
            json_error = f"Multiple JSON files found: {json_files}. Expected only one."
            logger.error(f"    ✗ {json_error}")
        else:
            json_filename = json_files[0]
            file_path = os.path.join(folder_path, json_filename)
            
            try:
                # Validate file access
                if not os.access(file_path, os.R_OK):
                    raise ValidationError(f"No read permission for JSON file: {json_filename}")
                
                if os.path.getsize(file_path) == 0:
                    raise ValidationError(f"JSON file is empty: {json_filename}")
                
                # Read and parse JSON
                with open(file_path, 'r', encoding='utf-8') as f:
                    json_data = json.load(f)
                
                # Validate JSON structure
                validate_json_structure(json_data, json_filename)
                
                # Prepare data for database insertion
                db_records = []
                
                if isinstance(json_data, dict):
                    # Single record
                    db_record = {
                        'folder_name': folder_name,
                        'data_type': json_data.get('data_type', 'device_test'),
                        'data': json_data,
                        'device_id': json_data.get('device_id'),
                        'device_name': json_data.get('device_name'),
                        'device_type': json_data.get('device_type'),
                        'test_results': json_data.get('test_results'),
                        'test_date': json_data.get('test_date'),
                        'test_status': json_data.get('test_status', 'pending'),
                        'upload_batch': json_data.get('upload_batch'),
                        'notes': json_data.get('notes'),
                        'metadata': json_data.get('metadata', {})
                    }
                    db_records.append(db_record)
                    
                elif isinstance(json_data, list):
                    # Multiple records
                    for item in json_data:
                        if isinstance(item, dict):
                            db_record = {
                                'folder_name': folder_name,
                                'data_type': item.get('data_type', 'device_test'),
                                'data': item,
                                'device_id': item.get('device_id'),
                                'device_name': item.get('device_name'),
                                'device_type': item.get('device_type'),
                                'test_results': item.get('test_results'),
                                'test_date': item.get('test_date'),
                                'test_status': item.get('test_status', 'pending'),
                                'upload_batch': item.get('upload_batch'),
                                'notes': item.get('notes'),
                                'metadata': item.get('metadata', {})
                            }
                            db_records.append(db_record)
                
                if db_records:
                    success, error_msg, records_inserted = insert_data_with_retry(
                        supabase, table_name, db_records
                    )
                    
                    if success:
                        logger.info(f"    ✓ Inserted {records_inserted} row(s) from {json_filename}")
                        json_upload_success = True
                    else:
                        json_error = f"Database insert failed: {error_msg}"
                        logger.error(f"    ✗ {json_error}")
                else:
                    json_error = "No valid records found in JSON"
                    logger.error(f"    ✗ {json_error}")
                    
            except json.JSONDecodeError as e:
                json_error = f"Error decoding JSON from {json_filename}: {e}"
                logger.error(f"    ✗ {json_error}")
            except ValidationError as e:
                json_error = str(e)
                logger.error(f"    ✗ {json_error}")
            except Exception as e:
                json_error = f"Error processing {json_filename}: {e}"
                logger.error(f"    ✗ {json_error}")
        
        # Upload images
        uploaded_images, failed_images, image_urls = upload_images_to_bucket(
            supabase, folder_path, folder_name, image_files
        )
        
        # Update database records with image URLs if both uploads were successful
        if json_upload_success and image_urls:
            try:
                success, error_msg, updated_count = update_records_with_images(
                    supabase, table_name, folder_name, image_urls
                )
                
                if success:
                    logger.info(f"    ✓ Updated {updated_count} record(s) with {len(image_urls)} image URLs")
                else:
                    logger.warning(f"    ⚠️  Warning: Failed to update records with image URLs: {error_msg}")
                    
            except Exception as e:
                logger.warning(f"    ⚠️  Warning: Failed to update records with image URLs: {e}")
        
        # Determine overall success
        overall_success = (
            json_upload_success and 
            len(failed_images) == 0 and 
            (len(image_files) == 0 or len(uploaded_images) > 0)
        )
        
        # Prepare result data
        result_data = {
            **metadata,
            "json_upload": {
                "success": json_upload_success,
                "filename": json_files[0] if json_files else None,
                "records_inserted": records_inserted,
                "error": json_error,
                "data_preview": str(json_data)[:200] + "..." if json_data and len(str(json_data)) > 200 else json_data
            },
            "image_upload": {
                "total_images": len(image_files),
                "successful_uploads": len(uploaded_images),
                "failed_uploads": len(failed_images),
                "uploaded_images": uploaded_images,
                "failed_images": failed_images
            },
            "summary": {
                "overall_success": overall_success,
                "total_files_processed": len(json_files) + len(image_files),
                "successful_operations": (1 if json_upload_success else 0) + len(uploaded_images),
                "failed_operations": (1 if json_error else 0) + len(failed_images)
            }
        }
        
        # Write result file
        filename = "upload_success.json" if overall_success else "upload_failed.json"
        result_written = write_result_file(folder_path, filename, result_data)
        
        if not result_written:
            logger.warning(f"    ⚠️  Could not write result file for {folder_name}")
        
        if overall_success:
            logger.info(f"    🎉 Folder {folder_name} processed successfully!")
        else:
            logger.warning(f"    ❌ Folder {folder_name} processed with errors!")
        
        return overall_success
        
    except UploadError as e:
        error_msg = f"Upload error processing {folder_name}: {e}"
        logger.error(f"    💥 {error_msg}")
        print(f"ERROR: {error_msg}")
        return False
    except Exception as e:
        error_msg = f"Unexpected error processing {folder_name}: {e}"
        logger.error(f"    💥 {error_msg}")
        print(f"ERROR: {error_msg}")
        return False

def update_records_with_images(supabase: Client, table_name: str, folder_name: str, 
                             image_urls: List[str], max_retries: int = 3) -> Tuple[bool, str, int]:
    """Update database records with image URLs"""
    for attempt in range(max_retries):
        try:
            response = supabase.table(table_name).update({'images': image_urls}).eq('folder_name', folder_name).execute()
            
            if hasattr(response, 'data') and response.data:
                return True, "", len(response.data)
            else:
                return False, "No records updated", 0
                
        except Exception as e:
            error_msg = f"Update attempt {attempt + 1}/{max_retries} failed: {e}"
            logger.warning(error_msg)
            
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.info(f"Retrying update in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                return False, f"All update attempts failed. Last error: {e}", 0
    
    return False, "Max retries exceeded", 0

def main():
    """Main function with comprehensive error handling"""
    try:
        logger.info("🚀 Starting Supabase upload script")
        
        # Validate environment
        validate_environment()
        
        # Supabase configuration - consider moving to environment variables
        url: str = "https://owcanqgrymdruzdrttfo.supabase.co"
        key: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im93Y2FucWdyeW1kcnV6ZHJ0dGZvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTAxMDk5NDgsImV4cCI6MjA2NTY4NTk0OH0.dTnDzGV86kttYh5fCzuQLTk3Klu9FkahEUMB0nLi60c"
        
        if not url or not key:
            error_msg = "Supabase URL and key must be provided"
            print(f"ERROR: {error_msg}")
            raise UploadError(error_msg)
        
        # Initialize Supabase client with options
        try:
            options = ClientOptions(
                auto_refresh_token=True,
                persist_session=True
            )
            supabase: Client = create_client(url, key, options)
            logger.info("✓ Supabase client initialized")
        except Exception as e:
            error_msg = f"Failed to initialize Supabase client: {e}"
            print(f"ERROR: {error_msg}")
            raise UploadError(error_msg)
        
        # Validate connection
        if not validate_supabase_connection(supabase):
            error_msg = "Cannot establish connection to Supabase"
            print(f"ERROR: {error_msg}")
            raise UploadError(error_msg)
        
        # Configuration
        parent_folder = "./sample"
        table_name = "device_test"
        
        # Allow command line argument for parent folder
        if len(sys.argv) > 1:
            parent_folder = sys.argv[1].strip()
            if not parent_folder:
                error_msg = "Parent folder path cannot be empty"
                print(f"ERROR: {error_msg}")
                raise UploadError(error_msg)
        
        # Validate parent folder
        parent_folder = os.path.abspath(parent_folder)
        
        logger.info(f"📋 Configuration:")
        logger.info(f"    Parent folder: '{parent_folder}'")
        logger.info(f"    Target table: {table_name}")
        logger.info(f"    Target bucket: devicetest")
        
        # Get subfolders to process
        try:
            folders_to_process = get_subfolders_to_process(parent_folder)
        except UploadError as e:
            error_msg = f"Error getting subfolders: {e}"
            logger.error(error_msg)
            print(f"ERROR: {error_msg}")
            return 1
        
        if not folders_to_process:
            logger.info("No subfolders found to process!")
            return 0
        
        # Counters for summary
        total_folders_processed = 0
        successful_folders = 0
        failed_folders = 0
        
        # Process each subfolder
        for folder_path, folder_name in folders_to_process:
            total_folders_processed += 1
            
            try:
                success = process_single_folder(supabase, folder_path, folder_name, table_name)
                if success:
                    successful_folders += 1
                else:
                    failed_folders += 1
                    
            except KeyboardInterrupt:
                logger.warning("Process interrupted by user")
                break
            except Exception as e:
                error_msg = f"Unexpected error processing {folder_name}: {e}"
                logger.error(f"💥 {error_msg}")
                print(f"ERROR: {error_msg}")
                failed_folders += 1
                continue
        
        # Final summary
        logger.info(f"\n" + "="*50)
        logger.info(f"📊 BATCH UPLOAD SUMMARY")
        logger.info(f"="*50)
        logger.info(f"Total folders found: {total_folders_processed}")
        logger.info(f"Successful uploads: {successful_folders}")
        logger.info(f"Failed uploads: {failed_folders}")
        
        if total_folders_processed > 0:
            success_rate = (successful_folders/total_folders_processed*100)
            logger.info(f"Overall success rate: {success_rate:.1f}%")
            
            if failed_folders > 0:
                logger.warning(f"⚠️  {failed_folders} folder(s) had errors - check upload_failed.json files")
                return 1
        else:
            logger.info("No subfolders found to process!")
        
        logger.info("✅ Script completed successfully")
        return 0
        
    except UploadError as e:
        error_msg = f"Upload error: {e}"
        logger.error(error_msg)
        print(f"ERROR: {error_msg}")
        return 1
    except KeyboardInterrupt:
        interrupt_msg = "Script interrupted by user"
        logger.warning(interrupt_msg)
        print(f"WARNING: {interrupt_msg}")
        return 1
    except Exception as e:
        error_msg = f"Unexpected error in main: {e}"
        logger.error(error_msg)
        print(f"ERROR: {error_msg}")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
