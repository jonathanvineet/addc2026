#!/usr/bin/env python3
"""
Windows Server API - Receive Images and Process with RealityScan
Receives images from Raspberry Pi and runs RealityScan for 3D reconstruction
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import subprocess
import threading
import time
import zipfile
import shutil
from pathlib import Path
from datetime import datetime
import logging
import json
import uuid
import sys

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = {
    # Server settings
    'HOST': '0.0.0.0',  # Listen on all interfaces
    'PORT': 5000,
    'DEBUG': False,
    
    # RealityScan settings
    'REALITYSCAN_EXE': r'c:\Program Files\Epic Games\RealityScan_2.1\RealityScan.exe',
    
    # Storage directories
    'BASE_DIR': r'C:\Users\Gaming\Pictures\Coding_Projects\Drone',
    'UPLOAD_DIR': r'C:\Users\Gaming\Pictures\Coding_Projects\Drone\uploads',
    'PROJECTS_DIR': r'C:\Users\Gaming\Pictures\Coding_Projects\Drone\projects',
    'RESULTS_DIR': r'C:\Users\Gaming\Pictures\Coding_Projects\Drone\results',
    
    # Processing settings
    'MAX_UPLOAD_SIZE': 500 * 1024 * 1024,  # 500 MB
    'ALLOWED_EXTENSIONS': {'.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG'},
}

# Create Flask app
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = CONFIG['MAX_UPLOAD_SIZE']
CORS(app)  # Enable CORS for cross-origin requests

# Setup logging with UTF-8 encoding (fixes emoji errors)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(CONFIG['BASE_DIR'], 'server.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Fix console encoding for Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass  # Python < 3.7

# Job tracking
jobs = {}
jobs_lock = threading.Lock()


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_directories():
    """Create necessary directories if they don't exist"""
    for dir_path in [CONFIG['UPLOAD_DIR'], CONFIG['PROJECTS_DIR'], CONFIG['RESULTS_DIR']]:
        os.makedirs(dir_path, exist_ok=True)
        logger.info(f"Directory ready: {dir_path}")


def generate_job_id():
    """Generate unique job ID"""
    return str(uuid.uuid4())


def get_job_status(job_id):
    """Get status of a job"""
    with jobs_lock:
        return jobs.get(job_id, None)


def update_job_status(job_id, status, progress=0, message=''):
    """Update job status"""
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id]['status'] = status
            jobs[job_id]['progress'] = progress
            jobs[job_id]['message'] = message
            jobs[job_id]['updated_at'] = datetime.now().isoformat()
            logger.info(f"Job {job_id}: {status} ({progress}%) - {message}")


def extract_zip(zip_path, extract_to):
    """Extract ZIP file"""
    logger.info(f"Extracting {zip_path} to {extract_to}")
    
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)
    
    # Count extracted files
    files = list(Path(extract_to).glob('*'))
    image_files = [f for f in files if f.suffix.lower() in CONFIG['ALLOWED_EXTENSIONS']]
    
    logger.info(f"Extracted {len(image_files)} images")
    return len(image_files)


def run_realityscan(project_id, images_folder, job_id):
    """Run RealityScan processing in background thread - MATCHES realityscan_align.py"""
    
    try:
        update_job_status(job_id, 'processing', 10, 'Preparing RealityScan...')
        
        # Ensure images folder has trailing backslash (IMPORTANT for RealityScan)
        if not images_folder.endswith('\\'):
            images_folder += '\\'
        
        # Output project file
        project_file = os.path.join(CONFIG['PROJECTS_DIR'], f"{project_id}.rsproj")
        
        # Build command - EXACT same structure as realityscan_align.py
        commands = []
        
        # Create new scene
        commands.append('-headless')
        commands.append('-newScene')
        
        # Add images from folder (with trailing backslash)
        commands.extend(['-addFolder', images_folder])
        
        # Detect features (recommended)
        commands.append('-detectFeatures')
        
        # Align images (full quality, not draft)
        commands.append('-align')
        
        # Select the best component
        commands.append('-selectMaximalComponent')
        
        # Save project
        commands.extend(['-save', project_file])
        
        # Quit
        commands.append('-quit')
        
        # Build command list - EXACT same as realityscan_align.py
        cmd_list = [CONFIG['REALITYSCAN_EXE']] + commands
        
        # For display purposes, show the command string
        display_parts = [f'"{CONFIG["REALITYSCAN_EXE"]}"']
        for cmd in commands:
            if ' ' in cmd and not cmd.startswith('-'):
                display_parts.append(f'"{cmd}"')
            else:
                display_parts.append(cmd)
        display_command = ' '.join(display_parts)
        
        logger.info(f"Executing RealityScan command:")
        logger.info(f"  {display_command}")
        
        update_job_status(job_id, 'processing', 20, 'Running feature detection...')
        
        # Execute RealityScan - EXACT same method as realityscan_align.py
        process = subprocess.Popen(
            cmd_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        logger.info(f"RealityScan started (PID: {process.pid})")
        update_job_status(job_id, 'processing', 40, 'Aligning images...')
        
        # Wait for completion - EXACT same as realityscan_align.py
        try:
            stdout, stderr = process.communicate(timeout=3600)  # 1 hour timeout
            
            # Log output for debugging
            if stdout:
                stdout_lines = stdout.split('\n')
                logger.debug(f"STDOUT ({len(stdout_lines)} lines):")
                for line in stdout_lines:
                    if line.strip():
                        logger.debug(f"  OUT: {line}")
            
            if stderr:
                stderr_lines = stderr.split('\n')
                logger.debug(f"STDERR ({len(stderr_lines)} lines):")
                for line in stderr_lines:
                    if line.strip():
                        logger.debug(f"  ERR: {line}")
        
        except subprocess.TimeoutExpired:
            logger.error(f"Job {job_id} timeout (1 hour exceeded)")
            process.kill()
            update_job_status(job_id, 'failed', 0, 'Processing timeout (1 hour)')
            return
        
        logger.info(f"RealityScan return code: {process.returncode}")
        
        # Check return code - EXACT same as realityscan_align.py
        if process.returncode != 0:
            error_msg = f"RealityScan failed with return code {process.returncode}"
            if stderr:
                error_msg += f" - Check logs for details"
            logger.error(error_msg)
            update_job_status(job_id, 'failed', 0, error_msg)
            return
        
        # Check if project file was created - EXACT same as realityscan_align.py
        if not os.path.exists(project_file):
            logger.error("Project file was not created")
            update_job_status(job_id, 'failed', 0, 'RealityScan did not create project file')
            return
        
        # Verify project file has content
        file_size = os.path.getsize(project_file)
        logger.info(f"Project file size: {file_size} bytes ({file_size/1024:.2f} KB)")
        
        # Check for project data folder - EXACT same as realityscan_align.py
        project_data_folder = project_file.replace('.rsproj', '')
        if not os.path.exists(project_data_folder):
            logger.warning(f"Project data folder not found: {project_data_folder}")
            logger.warning("Alignment may have failed - no point cloud generated")
            update_job_status(job_id, 'failed', 0, 'Alignment failed - no point cloud generated')
            return
        
        # Check for critical SfM files - EXACT same as realityscan_align.py
        sfm_files = list(Path(project_data_folder).glob('sfm*.dat'))
        if len(sfm_files) == 0:
            logger.error("No SfM data files found - alignment failed")
            update_job_status(job_id, 'failed', 0, 'Alignment failed - insufficient feature matches')
            return
        
        logger.info(f"✅ Found {len(sfm_files)} SfM data files - alignment successful!")
        
        update_job_status(job_id, 'processing', 80, 'Creating output package...')
        
        # Package results
        result_zip = package_results(project_id, project_file, job_id)
        
        if result_zip:
            update_job_status(job_id, 'completed', 100, 'Processing complete - 3D mesh ready for download')
            
            # Store result path in job info
            with jobs_lock:
                jobs[job_id]['result_path'] = result_zip
            
            logger.info(f"✅ Job {job_id} completed successfully")
        else:
            update_job_status(job_id, 'failed', 80, 'Failed to package results')
    
    except Exception as e:
        logger.error(f"Job {job_id} error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        update_job_status(job_id, 'error', 0, str(e))


def package_results(project_id, project_file, job_id):
    """Package the RealityScan project and results into a ZIP file"""
    
    try:
        # Create result directory
        result_dir = os.path.join(CONFIG['RESULTS_DIR'], project_id)
        os.makedirs(result_dir, exist_ok=True)
        
        # Output ZIP file
        result_zip = os.path.join(result_dir, f"{project_id}_result.zip")
        
        logger.info(f"Packaging results to: {result_zip}")
        
        with zipfile.ZipFile(result_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add project file
            if os.path.exists(project_file):
                zipf.write(project_file, arcname=os.path.basename(project_file))
                logger.info(f"Added project file: {os.path.basename(project_file)}")
            
            # Add project data folder (contains point cloud, etc.)
            project_data_folder = project_file.replace('.rsproj', '')
            if os.path.exists(project_data_folder):
                for root, dirs, files in os.walk(project_data_folder):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, os.path.dirname(project_file))
                        zipf.write(file_path, arcname=arcname)
                        logger.info(f"Added: {arcname}")
            
            # Add metadata
            metadata = {
                'project_id': project_id,
                'job_id': job_id,
                'created_at': datetime.now().isoformat(),
                'project_file': os.path.basename(project_file)
            }
            zipf.writestr('metadata.json', json.dumps(metadata, indent=2))
        
        logger.info(f"Result package created: {result_zip}")
        return result_zip
    
    except Exception as e:
        logger.error(f"Failed to package results: {e}")
        return None


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'server': 'RealityScan Processing Server',
        'timestamp': datetime.now().isoformat(),
        'realityscan_available': os.path.exists(CONFIG['REALITYSCAN_EXE'])
    })


@app.route('/api/process/upload', methods=['POST'])
def upload_images():
    """Receive batch of images from Raspberry Pi"""
    
    try:
        # Get form data
        project_id = request.form.get('project_id')
        batch_num = request.form.get('batch_num')
        total_batches = request.form.get('total_batches')
        image_count = request.form.get('image_count')
        
        logger.info(f"Received upload request for project {project_id}, batch {batch_num}/{total_batches}")
        
        # Validate
        if not project_id:
            return jsonify({'error': 'Missing project_id'}), 400
        
        if 'images' not in request.files:
            return jsonify({'error': 'No images file in request'}), 400
        
        file = request.files['images']
        
        if file.filename == '':
            return jsonify({'error': 'Empty filename'}), 400
        
        # Create project upload directory
        project_upload_dir = os.path.join(CONFIG['UPLOAD_DIR'], project_id)
        os.makedirs(project_upload_dir, exist_ok=True)
        
        # Save uploaded ZIP
        zip_path = os.path.join(project_upload_dir, f'batch_{batch_num}.zip')
        file.save(zip_path)
        
        logger.info(f"Saved batch {batch_num} to {zip_path}")
        
        # Extract images
        extract_dir = os.path.join(project_upload_dir, 'images')
        os.makedirs(extract_dir, exist_ok=True)
        
        extracted_count = extract_zip(zip_path, extract_dir)
        
        # Clean up ZIP file
        os.remove(zip_path)
        
        return jsonify({
            'status': 'success',
            'project_id': project_id,
            'batch_num': batch_num,
            'received_images': extracted_count,
            'message': f'Batch {batch_num}/{total_batches} received'
        })
    
    except Exception as e:
        logger.error(f"Upload error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@app.route('/api/process/start', methods=['POST'])
def start_processing():
    """Start RealityScan processing"""
    
    try:
        data = request.json
        project_id = data.get('project_id')
        quality = data.get('quality', 'high')
        
        logger.info(f"Starting processing for project {project_id}, quality={quality}")
        
        if not project_id:
            return jsonify({'error': 'Missing project_id'}), 400
        
        # Check if images exist
        images_folder = os.path.join(CONFIG['UPLOAD_DIR'], project_id, 'images')
        
        if not os.path.exists(images_folder):
            return jsonify({'error': 'Images not found for project'}), 404
        
        image_files = list(Path(images_folder).glob('*'))
        image_files = [f for f in image_files if f.suffix.lower() in CONFIG['ALLOWED_EXTENSIONS']]
        
        if len(image_files) == 0:
            return jsonify({'error': 'No valid images found'}), 400
        
        # Generate job ID
        job_id = generate_job_id()
        
        # Create job entry
        with jobs_lock:
            jobs[job_id] = {
                'job_id': job_id,
                'project_id': project_id,
                'status': 'queued',
                'progress': 0,
                'message': 'Job queued',
                'image_count': len(image_files),
                'quality': quality,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
                'result_path': None
            }
        
        # Start processing in background thread
        thread = threading.Thread(
            target=run_realityscan,
            args=(project_id, images_folder, job_id)
        )
        thread.daemon = True
        thread.start()
        
        logger.info(f"Started processing thread for job {job_id}")
        
        return jsonify({
            'status': 'success',
            'job_id': job_id,
            'project_id': project_id,
            'image_count': len(image_files),
            'message': 'Processing started'
        })
    
    except Exception as e:
        logger.error(f"Start processing error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@app.route('/api/process/status/<job_id>', methods=['GET'])
def get_status(job_id):
    """Get job status"""
    
    job_info = get_job_status(job_id)
    
    if job_info is None:
        return jsonify({'error': 'Job not found'}), 404
    
    # Return job info (excluding result_path for security)
    response = {k: v for k, v in job_info.items() if k != 'result_path'}
    
    return jsonify(response)


@app.route('/api/process/download/<job_id>', methods=['GET'])
def download_result(job_id):
    """Download the processed 3D mesh"""
    
    try:
        job_info = get_job_status(job_id)
        
        if job_info is None:
            return jsonify({'error': 'Job not found'}), 404
        
        if job_info['status'] != 'completed':
            return jsonify({'error': 'Job not completed yet'}), 400
        
        result_path = job_info.get('result_path')
        
        if not result_path or not os.path.exists(result_path):
            return jsonify({'error': 'Result file not found'}), 404
        
        logger.info(f"Sending result file for job {job_id}: {result_path}")
        
        return send_file(
            result_path,
            mimetype='application/zip',
            as_attachment=True,
            download_name=os.path.basename(result_path)
        )
    
    except Exception as e:
        logger.error(f"Download error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/process/jobs', methods=['GET'])
def list_jobs():
    """List all jobs"""
    
    with jobs_lock:
        jobs_list = list(jobs.values())
    
    return jsonify({
        'total': len(jobs_list),
        'jobs': jobs_list
    })


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Start the Flask server"""
    
    print("=" * 60)
    print("🖥️  REALITYSCAN PROCESSING SERVER")
    print("=" * 60)
    
    # Create directories
    create_directories()
    
    # Check RealityScan
    if not os.path.exists(CONFIG['REALITYSCAN_EXE']):
        logger.warning(f"⚠️  RealityScan not found at: {CONFIG['REALITYSCAN_EXE']}")
        logger.warning("Please update REALITYSCAN_EXE in CONFIG")
    else:
        logger.info(f"✅ RealityScan found: {CONFIG['REALITYSCAN_EXE']}")
    
    print("\n📡 Starting server...")
    print(f"   Host: {CONFIG['HOST']}")
    print(f"   Port: {CONFIG['PORT']}")
    print(f"\n🌐 API Endpoints:")
    print(f"   Health:   http://{CONFIG['HOST']}:{CONFIG['PORT']}/api/health")
    print(f"   Upload:   http://{CONFIG['HOST']}:{CONFIG['PORT']}/api/process/upload")
    print(f"   Start:    http://{CONFIG['HOST']}:{CONFIG['PORT']}/api/process/start")
    print(f"   Status:   http://{CONFIG['HOST']}:{CONFIG['PORT']}/api/process/status/<job_id>")
    print(f"   Download: http://{CONFIG['HOST']}:{CONFIG['PORT']}/api/process/download/<job_id>")
    print(f"   Jobs:     http://{CONFIG['HOST']}:{CONFIG['PORT']}/api/process/jobs")
    print("\n" + "=" * 60)
    print("Server ready! Press Ctrl+C to stop")
    print("=" * 60 + "\n")
    
    # Start Flask server
    app.run(
        host=CONFIG['HOST'],
        port=CONFIG['PORT'],
        debug=CONFIG['DEBUG'],
        threaded=True
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Server stopped by user")
    except Exception as e:
        print(f"\n❌ Server error: {e}")
        import traceback
        traceback.print_exc()