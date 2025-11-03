#!/usr/bin/env python3
"""
Process DICOM files and store metadata in database
Supports processing single directories or multiple scans in subdirectories
Also supports ZIP and 7Z archive files
"""

import sys
import tempfile
import shutil
import zipfile
from pathlib import Path
from extract_metadata import extract_all_metadata
from store_metadata import init_database

def process_single_scan(scan_dir: Path, conn, base_dir: Path):
    """Process a single scan directory and store in database"""
    from extract_metadata import extract_metadata
    from store_metadata import study_exists, insert_metadata
    
    # Find all DICOM files in this scan directory
    dcm_files = [
        f for f in scan_dir.rglob("*.dcm")
        if not f.name.startswith('._') and '__MACOSX' not in str(f)
    ]
    
    if not dcm_files:
        return 0, 0, 0, []
    
    # Process all files - let series-level deduplication handle existing series
    # This allows adding new series to existing studies
    processed = 0
    skipped_duplicates = 0
    skipped_invalid = 0
    new_studies = set()
    existing_studies = set()
    
    # Batch processing for efficiency - collect metadata first, then insert in batches
    batch_metadata = []
    batch_paths = []
    batch_size = 500  # Insert in batches of 500 for better performance
    
    for dcm_file in dcm_files:
        meta = extract_metadata(dcm_file)
        if meta:
            # Track which studies are new vs existing (for reporting only)
            if meta.study_instance_uid:
                if study_exists(conn, meta.study_instance_uid):
                    existing_studies.add(meta.study_instance_uid)
                else:
                    new_studies.add(meta.study_instance_uid)
            
            # Store relative path from base directory
            rel_path = str(dcm_file.relative_to(base_dir))
            batch_metadata.append(meta)
            batch_paths.append(rel_path)
            
            # Process batch when it reaches batch_size
            if len(batch_metadata) >= batch_size:
                for meta_item, file_path in zip(batch_metadata, batch_paths):
                    inserted, reason = insert_metadata(conn, meta_item, file_path, skip_existing=True, commit=False)
                    if inserted:
                        processed += 1
                    elif reason == "series_exists":
                        skipped_duplicates += 1
                    else:
                        skipped_invalid += 1
                # Commit batch
                conn.commit()
                batch_metadata.clear()
                batch_paths.clear()
        else:
            skipped_invalid += 1
    
    # Process remaining items in batch
    if batch_metadata:
        for meta_item, file_path in zip(batch_metadata, batch_paths):
            inserted, reason = insert_metadata(conn, meta_item, file_path, skip_existing=True, commit=False)
            if inserted:
                processed += 1
            elif reason == "series_exists":
                skipped_duplicates += 1
            else:
                skipped_invalid += 1
        conn.commit()
    
    return processed, skipped_duplicates, skipped_invalid, list(new_studies)


def process_directory(dicom_dir: str, db_path: str = "dicom_metadata.db", process_subdirs: bool = True):
    """Process all DICOM files in a directory, ZIP, or 7Z file and store metadata
    
    Args:
        dicom_dir: Directory containing DICOM files, subdirectories with scans, or a ZIP/7Z archive file
        db_path: Path to SQLite database file
        process_subdirs: If True, automatically process subdirectories as separate scans
    """
    dicom_path = Path(dicom_dir)
    
    if not dicom_path.exists():
        print(f"Error: Path {dicom_dir} does not exist")
        return
    
    # Check if input is a ZIP or 7Z file
    temp_extract_dir = None
    if dicom_path.is_file():
        filename_lower = dicom_path.name.lower()
        if filename_lower.endswith('.zip') or filename_lower.endswith('.7z'):
            print(f"📦 Detected archive file: {dicom_path.name}")
            print(f"   Extracting to temporary directory...")
            
            # Create temporary directory for extraction
            temp_extract_dir = tempfile.mkdtemp(prefix='dicom_process_')
            extract_dir = Path(temp_extract_dir)
            
            try:
                if filename_lower.endswith('.zip'):
                    # Extract ZIP file
                    with zipfile.ZipFile(dicom_path, 'r') as zip_ref:
                        zip_ref.extractall(extract_dir)
                    print(f"   ✓ Extracted ZIP file")
                elif filename_lower.endswith('.7z'):
                    # Extract 7Z file
                    try:
                        import py7zr
                        with py7zr.SevenZipFile(dicom_path, mode='r') as archive:
                            archive.extractall(extract_dir)
                        print(f"   ✓ Extracted 7Z file")
                    except ImportError:
                        # Fallback to system 7z command
                        import subprocess
                        result = subprocess.run(
                            ['7z', 'x', str(dicom_path), '-o' + str(extract_dir), '-y'],
                            capture_output=True,
                            text=True
                        )
                        if result.returncode != 0:
                            print(f"   ✗ Error: Failed to extract 7Z file")
                            print(f"   Install py7zr: pip install py7zr")
                            print(f"   Or ensure system 7z command is available")
                            try:
                                shutil.rmtree(temp_extract_dir)
                            except:
                                pass
                            return
                        print(f"   ✓ Extracted 7Z file (using system 7z)")
                
                # Update path to extracted directory
                dicom_path = extract_dir
                print()
            except Exception as e:
                print(f"   ✗ Error extracting archive: {e}")
                try:
                    shutil.rmtree(temp_extract_dir)
                except:
                    pass
                return
    
    # Now process as a directory (original logic continues)
    
    # Initialize database
    conn = init_database(db_path)
    
    # Check if directory contains subdirectories (works with any directory names)
    subdirs = [d for d in dicom_path.iterdir() if d.is_dir() and not d.name.startswith('.')]
    
    # Decide whether to process subdirectories or files directly
    if process_subdirs and subdirs:
        # Check if subdirectories contain DICOM files (generic check - works with any directory names)
        has_dicom_in_subdirs = False
        for subdir in subdirs:
            dcm_check = list(subdir.rglob("*.dcm"))
            if dcm_check:
                # Filter out macOS metadata files
                valid_dcm = [f for f in dcm_check if not f.name.startswith('._') and '__MACOSX' not in str(f)]
                if valid_dcm:
                    has_dicom_in_subdirs = True
                    break
        
        if has_dicom_in_subdirs:
            # Process each subdirectory as a separate scan
            print(f"📂 Processing multiple scans in: {dicom_path}")
            print(f"   Found {len(subdirs)} subdirectories\n")
            
            total_processed = 0
            total_skipped_duplicates = 0
            total_skipped_invalid = 0
            total_existing_studies = 0
            
            # First, check if there are DICOM files directly in the root directory
            root_dcm_files = [
                f for f in dicom_path.glob("*.dcm")
                if not f.name.startswith('._') and '__MACOSX' not in str(f)
            ]
            
            if root_dcm_files:
                print(f"   [0/{len(subdirs)+1}] Processing root directory files ({len(root_dcm_files)} file(s))")
                processed, skipped_dup, skipped_inv, new_studies = process_single_scan(dicom_path, conn, dicom_path)
                total_processed += processed
                total_skipped_duplicates += skipped_dup
                total_skipped_invalid += skipped_inv
                
                status_parts = []
                if processed > 0:
                    if new_studies:
                        status_parts.append(f"Added {processed} new files ({len(new_studies)} new study/studies)")
                    else:
                        status_parts.append(f"Added {processed} new series to existing study/studies")
                
                if skipped_dup > 0:
                    if processed == 0:
                        status_parts.append(f"All series already exist, skipped {skipped_dup} files")
                    else:
                        status_parts.append(f"Skipped {skipped_dup} duplicate series")
                
                if skipped_inv > 0:
                    status_parts.append(f"Skipped {skipped_inv} invalid files")
                
                if status_parts:
                    print(f"      ✓ {' | '.join(status_parts)}")
                else:
                    print(f"      ✓ Processed {processed} files")
                print()  # Blank line before subdirectories
            
            # Process each subdirectory as a separate scan
            for idx, scan_dir in enumerate(subdirs, 1):
                offset = 1 if root_dcm_files else 0
                print(f"   [{idx+offset}/{len(subdirs)+offset}] Processing: {scan_dir.name}")
                processed, skipped_dup, skipped_inv, new_studies = process_single_scan(scan_dir, conn, dicom_path)
                total_processed += processed
                total_skipped_duplicates += skipped_dup
                total_skipped_invalid += skipped_inv
                
                # Build status message
                status_parts = []
                if processed > 0:
                    if new_studies:
                        status_parts.append(f"Added {processed} new files ({len(new_studies)} new study/studies)")
                    else:
                        status_parts.append(f"Added {processed} new series to existing study/studies")
                
                if skipped_dup > 0:
                    if processed == 0:
                        status_parts.append(f"All series already exist, skipped {skipped_dup} files")
                    else:
                        status_parts.append(f"Skipped {skipped_dup} duplicate series")
                
                if skipped_inv > 0:
                    status_parts.append(f"Skipped {skipped_inv} invalid files")
                
                if status_parts:
                    print(f"      ✓ {' | '.join(status_parts)}")
                else:
                    print(f"      ✓ Processed {processed} files")
                
                # Track existing studies for summary
                if processed == 0 and skipped_dup > 0:
                    total_existing_studies += 1
            
            print(f"\n   ✅ Summary:")
            print(f"      • New files added: {total_processed}")
            if total_skipped_duplicates > 0:
                print(f"      • Duplicate files skipped: {total_skipped_duplicates}")
            if total_skipped_invalid > 0:
                print(f"      • Invalid files skipped: {total_skipped_invalid}")
            if total_existing_studies > 0:
                print(f"      • Scans already in database: {total_existing_studies}")
        else:
            # Process files directly (recursive)
            print(f"📂 Processing DICOM files in: {dicom_path} (recursive)")
            dcm_files = [
                f for f in dicom_path.rglob("*.dcm")
                if not f.name.startswith('._') and '__MACOSX' not in str(f)
            ]
            
            if not dcm_files:
                print("   ⚠️  No DICOM files found")
                conn.close()
                return
            
            print(f"   📄 Found {len(dcm_files)} DICOM files")
            
            processed = 0
            skipped_duplicates = 0
            skipped_invalid = 0
            from store_metadata import insert_metadata
            
            for dcm_file in dcm_files:
                from extract_metadata import extract_metadata
                meta = extract_metadata(dcm_file)
                if meta:
                    inserted, reason = insert_metadata(conn, meta, str(dcm_file.relative_to(dicom_path)), skip_existing=True)
                    if inserted:
                        processed += 1
                        if processed % 10 == 0:
                            print(f"   ✓ Processed {processed}/{len(dcm_files)} files...")
                    elif reason == "series_exists":
                        skipped_duplicates += 1
                    else:
                        skipped_invalid += 1
                else:
                    skipped_invalid += 1
            
            if skipped_duplicates > 0:
                print(f"   ⚠️  Skipped {skipped_duplicates} duplicate files")
            if skipped_invalid > 0:
                print(f"   ⚠️  Skipped {skipped_invalid} invalid files")
            
            print(f"   ✅ Added {processed} new files to database")
    else:
        # Process files directly (single directory or no subdirs)
        print(f"📂 Processing DICOM files in: {dicom_path}")
        dcm_files = [
            f for f in dicom_path.rglob("*.dcm")
            if not f.name.startswith('._') and '__MACOSX' not in str(f)
        ]
        
        if not dcm_files:
            print("   ⚠️  No DICOM files found")
            conn.close()
            # Clean up temporary directory if it was created
            if temp_extract_dir:
                try:
                    shutil.rmtree(temp_extract_dir)
                    print(f"   Cleaned up temporary extraction directory")
                except:
                    pass
            return
        
        print(f"   📄 Found {len(dcm_files)} DICOM files")
        
        processed = 0
        skipped_duplicates = 0
        skipped_invalid = 0
        from store_metadata import insert_metadata
        
        for dcm_file in dcm_files:
            from extract_metadata import extract_metadata
            meta = extract_metadata(dcm_file)
            if meta:
                inserted, reason = insert_metadata(conn, meta, str(dcm_file.relative_to(dicom_path)), skip_existing=True)
                if inserted:
                    processed += 1
                    if processed % 10 == 0:
                        print(f"   ✓ Processed {processed}/{len(dcm_files)} files...")
                elif reason == "series_exists":
                    skipped_duplicates += 1
                else:
                    skipped_invalid += 1
            else:
                skipped_invalid += 1
        
        if skipped_duplicates > 0:
            print(f"   ⚠️  Skipped {skipped_duplicates} duplicate files")
        if skipped_invalid > 0:
            print(f"   ⚠️  Skipped {skipped_invalid} invalid files")
        
        print(f"   ✅ Added {processed} new files to database")
    
    conn.close()
    print(f"\n   💾 Database saved to: {db_path}")
    
    # Clean up temporary directory if it was created from archive extraction
    if temp_extract_dir:
        try:
            print(f"   Cleaning up temporary extraction directory...")
            shutil.rmtree(temp_extract_dir)
            print(f"   ✓ Cleaned up")
        except Exception as e:
            print(f"   ⚠ Warning: Could not clean up temp directory: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 process_dicom.py <dicom_directory_or_archive> [database_path]")
        print("\nSupports:")
        print("  - Directories containing DICOM files")
        print("  - ZIP archive files (.zip)")
        print("  - 7Z archive files (.7z)")
        print("\nThe script automatically detects directory structure:")
        print("  - If subdirectories contain DICOM files, processes each as a separate scan")
        print("  - Otherwise, processes all DICOM files recursively")
        print("\nExamples:")
        print("  # Process a directory:")
        print("  python3 process_dicom.py /path/to/scan_directory dicom_metadata.db")
        print("  python3 process_dicom.py MIRROR_A")
        print("\n  # Process ZIP/7Z archive files:")
        print("  python3 process_dicom.py scan_data.zip")
        print("  python3 process_dicom.py scan_data.7z dicom_metadata.db")
        sys.exit(1)
    
    dicom_dir = sys.argv[1]
    db_path = sys.argv[2] if len(sys.argv) > 2 else "dicom_metadata.db"
    
    process_directory(dicom_dir, db_path)

