#!/usr/bin/env python3
"""
Clean Web UI for DICOM Metadata Browser
"""

from flask import Flask, render_template, request, jsonify
import sqlite3
from pathlib import Path
import os
import json
import re
import sys
import tempfile
import zipfile
import shutil
from difflib import SequenceMatcher
from process_dicom import process_directory

app = Flask(__name__)

# Default database path
DEFAULT_DB = "dicom_metadata.db"


def get_db_connection(db_path=None):
    """Get database connection"""
    if db_path is None:
        db_path = DEFAULT_DB
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def fuzzy_match(text1, text2, threshold=0.6):
    """Calculate similarity between two strings (0.0 to 1.0)"""
    if not text1 or not text2:
        return 0.0
    text1 = str(text1).lower().strip()
    text2 = str(text2).lower().strip()
    
    # Exact match
    if text1 == text2:
        return 1.0
    
    # Contains match
    if text1 in text2 or text2 in text1:
        return 0.9
    
    # Sequence similarity
    return SequenceMatcher(None, text1, text2).ratio()


def build_search_query(search_term):
    """Build SQL query with case-insensitive fuzzy search"""
    search_term = search_term.strip()
    
    # Convert search term to lowercase for consistent case-insensitive matching
    search_term_lower = search_term.lower()
    
    # Escape special characters for LIKE queries (%, _) - use double backslash for SQL escape
    escaped_term = search_term_lower.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    search_like = f"%{escaped_term}%"
    
    # Build WHERE clause with OR conditions across multiple fields
    # Case-insensitive search using LOWER() on both field and pattern
    # SQLite LIKE is case-insensitive by default, but LOWER() ensures it for all databases
    where_clause = """
        WHERE (
            LOWER(patient_name) LIKE ? ESCAPE '\\' OR
            LOWER(patient_id) LIKE ? ESCAPE '\\' OR
            LOWER(modality) LIKE ? ESCAPE '\\' OR
            LOWER(study_description) LIKE ? ESCAPE '\\' OR
            LOWER(manufacturer) LIKE ? ESCAPE '\\' OR
            LOWER(radiopharmaceutical) LIKE ? ESCAPE '\\' OR
            LOWER(study_id) LIKE ? ESCAPE '\\' OR
            LOWER(accession_number) LIKE ? ESCAPE '\\'
        )
    """
    
    query = f"""
        SELECT 
            study_instance_uid,
            patient_id,
            patient_name,
            study_date,
            study_time,
            study_description,
            modality,
            manufacturer,
            radiopharmaceutical,
            COUNT(*) as series_count
        FROM dicom_metadata
        {where_clause}
        GROUP BY study_instance_uid
        ORDER BY study_date DESC, study_time DESC
    """
    
    return query, [search_like] * 8


@app.route('/')
def index():
    """Main page - list all studies with optional search"""
    db_path = request.args.get('db', DEFAULT_DB)
    search_term = request.args.get('search', '').strip()
    deleted = request.args.get('deleted', '0')
    deleted_count = request.args.get('count', '0')
    
    if not os.path.exists(db_path):
        return render_template('index.html', studies=[], db_path=db_path, error="Database not found", search_term=search_term, deleted=deleted, deleted_count=deleted_count)
    
    try:
        conn = get_db_connection(db_path)
        
        if search_term:
            query, params = build_search_query(search_term)
            cursor = conn.execute(query, params)
            all_studies = [dict(row) for row in cursor.fetchall()]
            
            # Calculate match scores for ranking (but don't filter - SQL already found matches)
            search_lower = search_term.lower().strip()
            for study in all_studies:
                score = 0.0
                best_match_field = None
                
                fields_to_check = [
                    ('patient_name', study.get('patient_name', '')),
                    ('patient_id', study.get('patient_id', '')),
                    ('modality', study.get('modality', '')),
                    ('study_description', study.get('study_description', '')),
                    ('manufacturer', study.get('manufacturer', '')),
                    ('radiopharmaceutical', study.get('radiopharmaceutical', '')),
                ]
                
                for field_name, field_value in fields_to_check:
                    if field_value:
                        field_lower = str(field_value).lower()
                        # Exact match
                        if search_lower == field_lower:
                            score = max(score, 1.0)
                            best_match_field = field_name
                        # Contains match (SQL LIKE already found this, so this is likely)
                        elif search_lower in field_lower:
                            score = max(score, 0.95)
                            if not best_match_field:
                                best_match_field = field_name
                        elif field_lower in search_lower:
                            score = max(score, 0.9)
                            if not best_match_field:
                                best_match_field = field_name
                        # Fuzzy match for typo tolerance
                        else:
                            sim = fuzzy_match(search_lower, field_lower)
                            if sim > score:
                                score = max(score, sim)
                                if sim >= 0.7:  # Good fuzzy match
                                    best_match_field = field_name
                
                # If SQL found it but no good match, give it a baseline score
                if score == 0.0:
                    score = 0.5  # SQL found it, so it's a match, just not a great one
                
                study['match_score'] = score
                study['match_field'] = best_match_field
            
            # Sort by match score (best matches first)
            all_studies.sort(key=lambda x: x.get('match_score', 0), reverse=True)
            studies = all_studies
        else:
            cursor = conn.execute("""
                SELECT 
                    study_instance_uid,
                    patient_id,
                    patient_name,
                    study_date,
                    study_time,
                    study_description,
                    modality,
                    manufacturer,
                    radiopharmaceutical,
                    COUNT(*) as series_count
                FROM dicom_metadata
                GROUP BY study_instance_uid
                ORDER BY study_date DESC, study_time DESC
        """)
            studies = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        # Format dates and times
        for study in studies:
            if study.get('study_date'):
                study['study_date_formatted'] = format_date(study['study_date'])
            if study.get('study_time'):
                study['study_time_formatted'] = format_time(study['study_time'])
            # Clean up patient name display (remove DICOM delimiter characters ^)
            if study.get('patient_name'):
                # DICOM PatientName format is often: Last^First^Middle^Prefix^Suffix
                # For anonymized data like "Anonymous^00039^^^", show it cleaner
                parts = study['patient_name'].split('^')
                # If it's anonymized format (Anonymous^number), show it cleanly
                if len(parts) >= 2 and parts[0].lower() == 'anonymous':
                    study['patient_name_display'] = f"{parts[0]} {parts[1]}" if parts[1] else parts[0]
                else:
                    # Try to construct a readable name from parts
                    name_parts = [p for p in parts if p]  # Remove empty parts
                    study['patient_name_display'] = ' '.join(name_parts) if name_parts else study['patient_name']
            else:
                study['patient_name_display'] = None
        
        return render_template('index.html', studies=studies, db_path=db_path, search_term=search_term, deleted=deleted, deleted_count=deleted_count)
    except Exception as e:
        return render_template('index.html', studies=[], db_path=db_path, error=str(e), search_term=search_term, deleted=deleted, deleted_count=deleted_count)


@app.route('/study/<study_uid>')
def study_detail(study_uid):
    """Study detail page - show all series in a study"""
    db_path = request.args.get('db', DEFAULT_DB)
    
    if not os.path.exists(db_path):
        return f"Database not found: {db_path}", 404
    
    try:
        conn = get_db_connection(db_path)
        
        # Get study summary - aggregate patient info from all files in study
        # Use MAX() to get first non-null value for each field (works because same patient should have same values)
        cursor = conn.execute("""
            SELECT 
                study_instance_uid,
                MAX(patient_id) as patient_id,
                MAX(patient_name) as patient_name,
                MAX(patient_birth_date) as patient_birth_date,
                MAX(patient_sex) as patient_sex,
                MAX(patient_age) as patient_age,
                MAX(patient_weight) as patient_weight,
                MAX(patient_size) as patient_size,
                MAX(study_date) as study_date,
                MAX(study_time) as study_time,
                MAX(acquisition_date) as acquisition_date,
                MAX(acquisition_time) as acquisition_time,
                MAX(study_description) as study_description,
                MAX(study_id) as study_id,
                MAX(accession_number) as accession_number,
                MAX(referring_physician_name) as referring_physician_name,
                MAX(manufacturer) as manufacturer,
                MAX(manufacturer_model_name) as manufacturer_model_name,
                MAX(institution_name) as institution_name
            FROM dicom_metadata
            WHERE study_instance_uid = ?
            GROUP BY study_instance_uid
        """, (study_uid,))
        study_info = cursor.fetchone()
        
        if not study_info:
            conn.close()
            return f"Study not found: {study_uid}", 404
        
        study_info = dict(study_info)
        
        # Get all series in this study (including nuclear medicine fields)
        cursor = conn.execute("""
            SELECT 
                series_instance_uid,
                series_number,
                series_description,
                series_date,
                series_time,
                modality,
                body_part_examined,
                acquisition_date,
                acquisition_time,
                injection_time,
                injection_date,
                injected_activity,
                radiopharmaceutical,
                half_life,
                decay_correction,
                radiopharmaceutical_volume,
                radionuclide_total_dose,
                image_type,
                pixel_spacing,
                slice_thickness,
                manufacturer,
                manufacturer_model_name,
                software_version,
                station_name,
                file_path
            FROM dicom_metadata
            WHERE study_instance_uid = ?
            ORDER BY series_number ASC, series_time ASC
        """, (study_uid,))
        series = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        study_info = dict(study_info)
        
        # Format dates and times
        if study_info.get('study_date'):
            study_info['study_date_formatted'] = format_date(study_info['study_date'])
        if study_info.get('study_time'):
            study_info['study_time_formatted'] = format_time(study_info['study_time'])
        # Note: Acquisition date/time removed from study level - 
        # different series can have different acquisition times, 
        # so we show them per-series in the series table instead
        if study_info.get('patient_birth_date'):
            study_info['patient_birth_date_formatted'] = format_date(study_info['patient_birth_date'])
        
        # Clean up patient name display (remove DICOM delimiter characters ^)
        if study_info.get('patient_name'):
            parts = study_info['patient_name'].split('^')
            if len(parts) >= 2 and parts[0].lower() == 'anonymous':
                study_info['patient_name_display'] = f"{parts[0]} {parts[1]}" if parts[1] else parts[0]
            else:
                name_parts = [p for p in parts if p]  # Remove empty parts
                study_info['patient_name_display'] = ' '.join(name_parts) if name_parts else study_info['patient_name']
        else:
            study_info['patient_name_display'] = None
        
        # Calculate derived metrics (removed study-level nuclear medicine calculations)
        # Note: Nuclear medicine information is now per-series (see series loop below)
        
        # 5. BMI calculation (BMI = weight / height²)
        if study_info.get('patient_weight') and study_info.get('patient_size'):
            height_m = study_info['patient_size']
            if height_m and height_m > 0:
                bmi = study_info['patient_weight'] / (height_m * height_m)
                study_info['bmi'] = bmi
                study_info['height_cm'] = height_m * 100  # Convert to cm for display
        
        for s in series:
            if s.get('series_date'):
                s['series_date_formatted'] = format_date(s['series_date'])
            if s.get('series_time'):
                s['series_time_formatted'] = format_time(s['series_time'])
            if s.get('acquisition_date'):
                s['acquisition_date_formatted'] = format_date(s['acquisition_date'])
            if s.get('acquisition_time'):
                s['acquisition_time_formatted'] = format_time(s['acquisition_time'])
                
                # Check if acquisition time suggests next day
                if study_info.get('study_time') and s.get('acquisition_time'):
                    try:
                        study_hours = int(str(study_info['study_time'])[:2])
                        acq_hours = int(str(s['acquisition_time'])[:2])
                        # If study is late (>= 22:00) and acquisition is early (<= 06:00), likely next day
                        if study_hours >= 22 and acq_hours <= 6:
                            s['acquisition_likely_next_day'] = True
                    except:
                        pass
            if s.get('injection_date'):
                s['injection_date_formatted'] = format_date(s['injection_date'])
            if s.get('injection_time'):
                s['injection_time_formatted'] = format_time(s['injection_time'])
            
            # Calculate injection-to-acquisition delay for this series
            # Use study_date as fallback if injection_date is missing (injection usually same day as study)
            # Use acquisition_date as primary, study_date as fallback
            injection_date_to_use = s.get('injection_date') or study_info.get('study_date')
            acquisition_date_to_use = s.get('acquisition_date') or study_info.get('study_date')
            
            if (injection_date_to_use and s.get('injection_time') and 
                acquisition_date_to_use and s.get('acquisition_time')):
                delay_minutes = calculate_injection_delay(
                    injection_date_to_use,
                    s['injection_time'],
                    acquisition_date_to_use,
                    s['acquisition_time'],
                    injection_date_missing=(s.get('injection_date') is None)
                )
                if delay_minutes:
                    s['injection_delay'] = format_delay(delay_minutes)
                    s['injection_delay_minutes'] = delay_minutes
            
            # Calculate activity per kg body weight for this series
            if s.get('injected_activity') and study_info.get('patient_weight'):
                activity_per_kg = s['injected_activity'] / study_info['patient_weight']
                s['activity_per_kg'] = activity_per_kg
            
            # Calculate remaining activity at scan time for this series
            # Use the injection delay we calculated above
            if (s.get('injected_activity') and s.get('half_life') and 
                s.get('injection_delay_minutes')):
                remaining_activity = calculate_activity_at_scan(
                    s['injected_activity'],
                    s['half_life'],
                    s['injection_delay_minutes']
                )
                if remaining_activity:
                    s['activity_at_scan'] = remaining_activity
                    if s['injected_activity'] and s['injected_activity'] > 0:
                        decay_percent = (1 - remaining_activity / s['injected_activity']) * 100
                        s['decay_percent'] = decay_percent
        
        return render_template('study_detail.html', 
                             study_info=study_info, 
                             series=series,
                             db_path=db_path)
    except Exception as e:
        return f"Error: {str(e)}", 500


@app.route('/study/<study_uid>/delete', methods=['POST'])
def delete_study(study_uid):
    """Delete a study and all its series from the database"""
    db_path = request.args.get('db', DEFAULT_DB)
    
    if not os.path.exists(db_path):
        return f"Database not found: {db_path}", 404
    
    try:
        conn = get_db_connection(db_path)
        
        # Check if study exists
        cursor = conn.execute(
            "SELECT COUNT(*) FROM dicom_metadata WHERE study_instance_uid = ?",
            (study_uid,)
        )
        count = cursor.fetchone()[0]
        
        if count == 0:
            conn.close()
            return f"Study not found: {study_uid}", 404
        
        # Delete all series in this study
        cursor = conn.execute(
            "DELETE FROM dicom_metadata WHERE study_instance_uid = ?",
            (study_uid,)
        )
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        # Redirect back to index page with success message
        from flask import redirect, url_for
        return redirect(f"/?db={db_path}&deleted=1&count={deleted_count}")
    
    except Exception as e:
        return f"Error deleting study: {str(e)}", 500


@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle ZIP/7Z file upload and process DICOM files"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': 'No file provided'}), 400
        
        file = request.files['file']
        db_path = request.form.get('db', DEFAULT_DB)
        
        if file.filename == '':
            return jsonify({'success': False, 'message': 'No file selected'}), 400
        
        # Check file extension
        filename = file.filename.lower()
        if not (filename.endswith('.zip') or filename.endswith('.7z')):
            return jsonify({'success': False, 'message': 'Only ZIP and 7Z files are supported'}), 400
        
        # Create temporary directory for extraction
        temp_dir = tempfile.mkdtemp(prefix='dicom_upload_')
        
        try:
            # Save uploaded file
            uploaded_path = os.path.join(temp_dir, file.filename)
            file.save(uploaded_path)
            
            # Extract archive
            extract_dir = os.path.join(temp_dir, 'extracted')
            os.makedirs(extract_dir, exist_ok=True)
            
            if filename.endswith('.zip'):
                # Extract ZIP file
                with zipfile.ZipFile(uploaded_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
            elif filename.endswith('.7z'):
                # Extract 7Z file - try py7zr first, fallback to system 7z command
                try:
                    import py7zr
                    with py7zr.SevenZipFile(uploaded_path, mode='r') as archive:
                        archive.extractall(extract_dir)
                except ImportError:
                    # Fallback to system 7z command if py7zr not available
                    import subprocess
                    result = subprocess.run(
                        ['7z', 'x', uploaded_path, '-o' + extract_dir, '-y'],
                        capture_output=True,
                        text=True
                    )
                    if result.returncode != 0:
                        return jsonify({
                            'success': False, 
                            'message': f'Failed to extract 7Z file. Install py7zr (pip install py7zr) or system 7z command.'
                        }), 400
            
            # Process extracted DICOM files using existing process_directory function
            # This will handle all the processing, deduplication, and counting
            try:
                process_directory(extract_dir, db_path=db_path, process_subdirs=True)
                
                # Get summary from database - count new files added
                conn = get_db_connection(db_path)
                cursor = conn.execute("SELECT COUNT(*) FROM dicom_metadata")
                total_files = cursor.fetchone()[0]
                conn.close()
                
                return jsonify({
                    'success': True,
                    'message': f'Archive processed successfully. Check the studies list below.'
                })
                
            except Exception as e:
                return jsonify({
                    'success': False,
                    'message': f'Error processing DICOM files: {str(e)}'
                }), 500
        
        finally:
            # Clean up temporary directory
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                print(f"Warning: Failed to clean up temp directory {temp_dir}: {e}")
    
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Upload error: {str(e)}'
        }), 500


@app.route('/api/series/<series_uid>')
def series_detail(series_uid):
    """API endpoint to get detailed series information"""
    db_path = request.args.get('db', DEFAULT_DB)
    
    if not os.path.exists(db_path):
        return jsonify({"error": "Database not found"}), 404
    
    try:
        conn = get_db_connection(db_path)
        cursor = conn.execute("""
            SELECT * FROM dicom_metadata
            WHERE series_instance_uid = ?
        """, (series_uid,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return jsonify({"error": "Series not found"}), 404
        
        return jsonify(dict(row))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def format_date(date_str):
    """Format DICOM date (YYYYMMDD) to DD/MM/YYYY format"""
    if not date_str or len(date_str) < 8:
        return date_str
    try:
        # DICOM format: YYYYMMDD
        year = date_str[:4]
        month = date_str[4:6]
        day = date_str[6:8]
        return f"{day}/{month}/{year}"
    except:
        return date_str


def format_time(time_str):
    """Format DICOM time (HHMMSS.frac) to human-readable format (HH:MM:SS)"""
    if not time_str:
        return time_str
    try:
        # Handle string or numeric input
        time_str = str(time_str).strip()
        
        # DICOM TM format: HHMMSS[.frac] - at least 6 digits
        if len(time_str) >= 6:
            hours = time_str[:2]
            minutes = time_str[2:4]
            seconds = time_str[4:6]
            
            # Handle fractional seconds if present
            if '.' in time_str and len(time_str) > 6:
                # Extract fractional part but don't display (optional)
                frac_part = time_str.split('.', 1)[1]
                if frac_part:
                    # Show seconds with 1 decimal place if fractional part exists
                    return f"{hours}:{minutes}:{seconds}.{frac_part[:1]}"
            
            return f"{hours}:{minutes}:{seconds}"
        return time_str
    except Exception:
        return time_str


def parse_time_to_seconds(time_str):
    """Convert DICOM time (HHMMSS.frac) to seconds since midnight"""
    if not time_str:
        return None
    try:
        time_str = str(time_str).strip()
        if len(time_str) >= 6:
            hours = int(time_str[:2])
            minutes = int(time_str[2:4])
            seconds = int(time_str[4:6])
            total_seconds = hours * 3600 + minutes * 60 + seconds
            
            # Add fractional part if present
            if '.' in time_str:
                frac = float(time_str.split('.', 1)[1])
                total_seconds += frac
            
            return total_seconds
    except Exception:
        return None


def parse_date_to_days(date_str):
    """Convert DICOM date (YYYYMMDD) to days since epoch for calculations"""
    if not date_str or len(date_str) < 8:
        return None
    try:
        from datetime import datetime
        year = int(date_str[:4])
        month = int(date_str[4:6])
        day = int(date_str[6:8])
        dt = datetime(year, month, day)
        return (dt - datetime(1970, 1, 1)).days
    except Exception:
        return None


def calculate_injection_delay(injection_date, injection_time, acquisition_date, acquisition_time, injection_date_missing=False):
    """Calculate delay between injection and acquisition in minutes"""
    if not injection_date or not injection_time or not acquisition_date or not acquisition_time:
        return None
    
    try:
        from datetime import datetime, timedelta
        
        # Parse injection datetime
        inj_date_str = str(injection_date).strip()
        # Handle fractional seconds in time (remove .000000)
        inj_time_str = str(injection_time).strip()
        # Extract just the integer part before any decimal point
        if '.' in inj_time_str:
            inj_time_str = inj_time_str.split('.')[0]
        
        if len(inj_date_str) >= 8 and len(inj_time_str) >= 6:
            inj_year = int(inj_date_str[:4])
            inj_month = int(inj_date_str[4:6])
            inj_day = int(inj_date_str[6:8])
            inj_hour = int(inj_time_str[:2])
            inj_min = int(inj_time_str[2:4])
            inj_sec = int(inj_time_str[4:6]) if len(inj_time_str) >= 6 else 0
            injection_dt = datetime(inj_year, inj_month, inj_day, inj_hour, inj_min, inj_sec)
        else:
            return None
        
        # Parse acquisition datetime
        acq_date_str = str(acquisition_date).strip()
        # Handle fractional seconds in time (remove .000000)
        acq_time_str = str(acquisition_time).strip()
        # Extract just the integer part before any decimal point
        if '.' in acq_time_str:
            acq_time_str = acq_time_str.split('.')[0]
        
        if len(acq_date_str) >= 8 and len(acq_time_str) >= 6:
            acq_year = int(acq_date_str[:4])
            acq_month = int(acq_date_str[4:6])
            acq_day = int(acq_date_str[6:8])
            acq_hour = int(acq_time_str[:2])
            acq_min = int(acq_time_str[2:4])
            acq_sec = int(acq_time_str[4:6]) if len(acq_time_str) >= 6 else 0
            acquisition_dt = datetime(acq_year, acq_month, acq_day, acq_hour, acq_min, acq_sec)
        else:
            return None
        
        # Handle date rollover scenarios:
        # If acquisition time is earlier in the day than injection time AND acquisition is early morning,
        # acquisition is likely the next day (common in nuclear medicine where injection happens afternoon,
        # patient waits, then scan happens early next morning)
        needs_rollover = False
        
        # Calculate time comparison (injection at 13:29 vs acquisition at 05:24)
        # If injection hour > acquisition hour by a significant amount (and acquisition is early morning),
        # it's likely next day
        if injection_date == acquisition_date:
            # Same date string - check if times suggest rollover
            # Case 1: Injection late night (>= 22:00) and acquisition early morning (<= 06:00)
            if inj_hour >= 22 and acq_hour <= 6:
                needs_rollover = True
            # Case 2: Injection is afternoon/evening (>= 12:00) and acquisition is early morning (<= 08:00)
            # AND injection time is later than acquisition time
            elif inj_hour >= 12 and acq_hour <= 8 and inj_hour > acq_hour:
                needs_rollover = True
            # Case 3: Any time where injection is clearly later in day than acquisition
            # (e.g., injection 14:00, acquisition 06:00)
            elif inj_hour > acq_hour and acq_hour <= 8:
                needs_rollover = True
        elif injection_date_missing:
            # If injection_date was missing, we used study_date
            # Same logic: if injection is afternoon/evening and acquisition is early morning, likely next day
            if inj_hour >= 12 and acq_hour <= 8:
                needs_rollover = True
        
        if needs_rollover:
            acquisition_dt = acquisition_dt + timedelta(days=1)
        
        # Calculate difference
        delay = acquisition_dt - injection_dt
        delay_minutes = delay.total_seconds() / 60
        
        # Only return positive delays (ignore negative delays which suggest data inconsistency)
        if delay_minutes < 0:
            return None
        
        return delay_minutes
    except Exception as e:
        return None


def calculate_patient_age(birth_date, study_date):
    """Calculate patient age in years from birth date and study date"""
    if not birth_date or not study_date:
        return None
    
    try:
        from datetime import datetime
        
        birth_str = str(birth_date).strip()
        study_str = str(study_date).strip()
        
        if len(birth_str) >= 8 and len(study_str) >= 8:
            birth_dt = datetime(int(birth_str[:4]), int(birth_str[4:6]), int(birth_str[6:8]))
            study_dt = datetime(int(study_str[:4]), int(study_str[4:6]), int(study_str[6:8]))
            
            age = (study_dt - birth_dt).days / 365.25
            return age
    except Exception:
        return None


def calculate_activity_at_scan(injected_activity, half_life_seconds, delay_minutes):
    """Calculate remaining activity at time of scan (with decay)"""
    if not injected_activity or not half_life_seconds or not delay_minutes or half_life_seconds <= 0:
        return None
    
    try:
        import math
        # Activity = A0 * e^(-lambda * t)
        # where lambda = ln(2) / half_life
        lambda_decay = math.log(2) / half_life_seconds
        time_seconds = delay_minutes * 60
        remaining_activity = injected_activity * math.exp(-lambda_decay * time_seconds)
        return remaining_activity
    except Exception:
        return None


def format_delay(minutes):
    """Format delay in minutes to human-readable format"""
    if minutes is None:
        return None
    
    try:
        if minutes < 60:
            return f"{minutes:.1f} minutes"
        elif minutes < 1440:  # Less than 24 hours
            hours = minutes / 60
            return f"{hours:.1f} hours ({minutes:.0f} min)"
        else:
            days = minutes / 1440
            return f"{days:.1f} days ({minutes:.0f} min)"
    except Exception:
        return None


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print(f"Starting DICOM Metadata Browser on http://127.0.0.1:{port}")
    print(f"Using database: {DEFAULT_DB}")
    app.run(debug=False, host='127.0.0.1', port=port)

