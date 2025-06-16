#!/usr/bin/env python3
"""
Supabase Upload Script
Processes subfolders and uploads JSON files to device_test table and images to device_test bucket in Supabase
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from supabase import create_client, Client

def get_subfolders_to_process(parent_folder):
    """Generator that yields subfolders sorted by latest modification time first, skipping already processed ones"""
    if not os.path.exists(parent_folder):
        print(f"Error: Parent folder '{parent_folder}' not found")
        return
    
    # Get all subdirectories
    subfolders = []
    for item in os.listdir(parent_folder):
        item_path = os.path.join(parent_folder, item)
        if os.path.isdir(item_path):
            # Check if already processed (has upload_success.json)
            success_file = os.path.join(item_path, "upload_success.json")
            if os.path.exists(success_file):
                print(f"⏭️  Skipping {item} - already processed (upload_success.json found)")
                continue
            
            # Get modification time
            mod_time = os.path.getmtime(item_path)
            subfolders.append((item_path, mod_time, item))
    
    # Sort by modification time (latest first)
    subfolders.sort(key=lambda x: x[1], reverse=True)
    
    print(f"Found {len(subfolders)} subfolder(s) to process (sorted by latest first)")
    
    # Yield folders one by one
    for folder_path, mod_time, folder_name in subfolders:
        yield folder_path, folder_name

def get_image_files(folder_path):
    """Get all image files from the folder"""
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}
    image_files = []
    
    for filename in os.listdir(folder_path):
        if Path(filename).suffix.lower() in image_extensions:
            image_files.append(filename)
    
    return image_files

def upload_images_to_bucket(supabase, folder_path, folder_name, image_files):
    """Upload images to Supabase storage bucket and return their public URLs"""
    bucket_name = "devicetest"
    uploaded_images = []
    failed_images = []
    image_urls = []
    
    for image_file in image_files:
        try:
            file_path = os.path.join(folder_path, image_file)
            
            # Create storage path: folder_name/image_file
            storage_path = f"{folder_name}/{image_file}"
            
            with open(file_path, 'rb') as f:
                file_data = f.read()
            
            # Upload to bucket
            response = supabase.storage.from_(bucket_name).upload(
                path=storage_path,
                file=file_data,
                file_options={"content-type": f"image/{Path(image_file).suffix[1:]}"}
            )
            
            # Get public URL for the uploaded image
            public_url = supabase.storage.from_(bucket_name).get_public_url(storage_path)
            image_urls.append(public_url)
            
            uploaded_images.append({
                "filename": image_file,
                "storage_path": storage_path,
                "public_url": public_url,
                "size_bytes": len(file_data)
            })
            print(f"    ✓ Uploaded image: {image_file} -> {public_url}")
            
        except Exception as e:
            failed_images.append({
                "filename": image_file,
                "error": str(e)
            })
            print(f"    ✗ Failed to upload image {image_file}: {e}")
    
    return uploaded_images, failed_images, image_urls

def write_result_file(folder_path, filename, data):
    """Write result data to JSON file in the specific folder"""
    try:
        result_file_path = os.path.join(folder_path, filename)
        with open(result_file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"    ✓ Result file written: {result_file_path}")
    except Exception as e:
        print(f"    ✗ Failed to write result file {filename}: {e}")

def process_single_folder(supabase, folder_path, folder_name, table_name):
    """Process a single folder - upload JSON and images"""
    print(f"\n📁 Processing folder: {folder_name}")
    
    # Get files (exclude result files from previous runs)
    excluded_json_files = {'upload_success.json', 'upload_failed.json'}
    json_files = [f for f in os.listdir(folder_path) 
                  if f.endswith('.json') and f not in excluded_json_files]
    image_files = get_image_files(folder_path)
    
    print(f"    Found {len(json_files)} JSON file(s) and {len(image_files)} image(s)")
    
    # Metadata for result files
    timestamp = datetime.now().isoformat()
    metadata = {
        "timestamp": timestamp,
        "folder_name": folder_name,
        "folder_path": folder_path,
        "table_name": table_name,
        "bucket_name": "device_test"
    }
    
    # Process JSON file (expecting only one)
    json_upload_success = False
    json_data = None
    json_error = None
    
    if len(json_files) == 0:
        json_error = "No JSON files found in folder"
        print(f"    ✗ No JSON files found in {folder_path}")
    elif len(json_files) > 1:
        json_error = f"Multiple JSON files found: {json_files}. Expected only one."
        print(f"    ✗ {json_error}")
    else:
        json_filename = json_files[0]
        file_path = os.path.join(folder_path, json_filename)
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            
            # Prepare data for database insertion
            if isinstance(json_data, dict):
                # Single record - structure it properly for the schema
                db_record = {
                    'folder_name': folder_name,
                    'data_type': json_data.get('data_type', 'device_test'),
                    'data': json_data,  # Store the full JSON as data
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
                response = supabase.table(table_name).insert(db_record).execute()
                print(f"    ✓ Inserted 1 row from {json_filename}")
                json_upload_success = True
            elif isinstance(json_data, list):
                # Multiple records - structure each one
                db_records = []
                for item in json_data:
                    if isinstance(item, dict):
                        db_record = {
                            'folder_name': folder_name,
                            'data_type': item.get('data_type', 'device_test'),
                            'data': item,  # Store the full JSON as data
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
                    response = supabase.table(table_name).insert(db_records).execute()
                    print(f"    ✓ Inserted {len(db_records)} rows from {json_filename}")
                    json_upload_success = True
                else:
                    json_error = "No valid records found in JSON array"
                    print(f"    ✗ {json_error}")
            else:
                json_error = f"Unsupported JSON format in {json_filename} (not dict or list)"
                print(f"    ✗ {json_error}")
                
        except json.JSONDecodeError as e:
            json_error = f"Error decoding JSON from {json_filename}: {e}"
            print(f"    ✗ {json_error}")
        except Exception as e:
            json_error = f"Error uploading {json_filename}: {e}"
            print(f"    ✗ {json_error}")
    
    # Upload images first to get URLs
    uploaded_images, failed_images, image_urls = upload_images_to_bucket(
        supabase, folder_path, folder_name, image_files
    )
    
    # Update database records with image URLs if upload was successful
    if json_upload_success and image_urls:
        try:
            # Update all records for this folder with the image URLs
            response = supabase.table(table_name).update({'images': image_urls}).eq('folder_name', folder_name).execute()
            records_updated = len(response.data) if response.data else 0
            print(f"    ✓ Updated {records_updated} record(s) with {len(image_urls)} image URLs")
        except Exception as e:
            print(f"    ⚠️  Warning: Failed to update records with image URLs: {e}")
    
    # Determine overall success
    overall_success = json_upload_success and len(failed_images) == 0
    
    # Prepare result data
    result_data = {
        **metadata,
        "json_upload": {
            "success": json_upload_success,
            "filename": json_files[0] if json_files else None,
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
    
    # Write result file in the folder
    if overall_success:
        write_result_file(folder_path, "upload_success.json", result_data)
        print(f"    🎉 Folder {folder_name} processed successfully!")
    else:
        write_result_file(folder_path, "upload_failed.json", result_data)
        print(f"    ❌ Folder {folder_name} processed with errors!")
    
    return overall_success

def main():
    # Supabase configuration
    url: str = "https://owcanqgrymdruzdrttfo.supabase.co"
    key: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im93Y2FucWdyeW1kcnV6ZHJ0dGZvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTAxMDk5NDgsImV4cCI6MjA2NTY4NTk0OH0.dTnDzGV86kttYh5fCzuQLTk3Klu9FkahEUMB0nLi60c"
    
    # Initialize Supabase client
    supabase: Client = create_client(url, key)
    
    # Parent folder containing subfolders to process
    parent_folder = "./sample"  # Current directory by default, change as needed
    table_name = "device_test"
    
    # Allow command line argument for parent folder
    if len(sys.argv) > 1:
        parent_folder = sys.argv[1]
    
    print(f"🚀 Starting batch upload from parent folder: '{parent_folder}'")
    print(f"📋 Target table: {table_name}")
    print(f"🗄️  Target bucket: device_test")
    
    # Counters for summary
    total_folders_processed = 0
    successful_folders = 0
    failed_folders = 0
    
    # Process each subfolder using generator
    for folder_path, folder_name in get_subfolders_to_process(parent_folder):
        total_folders_processed += 1
        
        try:
            success = process_single_folder(supabase, folder_path, folder_name, table_name)
            if success:
                successful_folders += 1
            else:
                failed_folders += 1
        except Exception as e:
            print(f"    💥 Unexpected error processing {folder_name}: {e}")
            failed_folders += 1
    
    # Final summary
    print(f"\n" + "="*50)
    print(f"📊 BATCH UPLOAD SUMMARY")
    print(f"="*50)
    print(f"Total folders found: {total_folders_processed}")
    print(f"Successful uploads: {successful_folders}")
    print(f"Failed uploads: {failed_folders}")
    print(f"Overall success rate: {(successful_folders/total_folders_processed*100):.1f}%" if total_folders_processed > 0 else "N/A")
    
    if total_folders_processed == 0:
        print("No subfolders found to process!")

if __name__ == "__main__":
    main()
