#!/usr/bin/env python3
"""
UNIFIED DRONE CONTROLLER
Combines QR detection, servo control, video streaming, and Windows server API communication
Uses ONE camera feed for all operations
"""

import os
import warnings
import logging

# Suppress warnings
warnings.filterwarnings('ignore')
logging.getLogger('tensorflow').setLevel(logging.ERROR)
logging.getLogger('matplotlib').setLevel(logging.ERROR)
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['OPENCV_LOG_LEVEL'] = 'ERROR'
os.environ['OPENCV_VIDEOIO_DEBUG'] = '0'

from pymavlink import mavutil
import cv2
import time
import RPi.GPIO as GPIO
from pyzbar.pyzbar import decode
import threading
from queue import Queue
import numpy as np
from flask import Flask, Response
import requests
import io

# ================= CONFIG =================

# Mavlink
PORT = '/dev/ttyACM0'

# QR Detection
VALID_QR_TEXT = "SCANNED"
QR_CONFIRM_FRAMES = 2

# Servo
SERVO_GPIO = 18        # BCM pin
SERVO_FREQ = 50        # 50Hz
SERVO_NEUTRAL = 2.5
SERVO_TRIGGER = 7.5

# Camera & Processing
FRAME_QUEUE_SIZE = 10
NUM_DETECTION_THREADS = 2
CAMERA_ID = 0
FRAME_WIDTH = 1280
FRAME_HEIGHT = 720
CAMERA_FPS = 30

# Flask Server (for ngrok streaming)
FLASK_HOST = '0.0.0.0'
FLASK_PORT = 5000

# Windows Server API
WINDOWS_SERVER_IP = "192.168.43.24"
WINDOWS_SERVER_PORT = 5000
WINDOWS_SERVER_URL = f'http://{WINDOWS_SERVER_IP}:{WINDOWS_SERVER_PORT}'
JPEG_QUALITY = 85
SEND_TO_WINDOWS = True  # Set to False to disable sending to Windows server

# Display Mode
HEADLESS_MODE = True  # Set to True for boot operation (no cv2.imshow), False for testing with monitor

# Logging
LOG_FILE = f"drone_log_{int(time.time())}.txt"

# =========================================

# ================= LOGGING SETUP =================

def log_message(message, also_print=True, level="INFO"):
    """Log message to file and optionally print to console"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] [{level}] {message}\n"
    
    with open(LOG_FILE, 'a') as f:
        f.write(log_entry)
    
    if also_print:
        # Clean terminal output - only essential messages with icons
        if level in ["OK", "QR", "ACTION", "ERROR", "SUMMARY"]:
            icon = {
                "OK": "✓",
                "QR": "📷",
                "ACTION": "🎯",
                "ERROR": "❌",
                "SUMMARY": "📊"
            }.get(level, "•")
            print(f"{icon} {message}")
        elif level == "INFO":
            print(f"  {message}")

# ================= GPIO SETUP =================

GPIO.setmode(GPIO.BCM)
GPIO.setup(SERVO_GPIO, GPIO.OUT)

servo = GPIO.PWM(SERVO_GPIO, SERVO_FREQ)
servo.start(0)

def trigger_servo():
    log_message("Servo triggered", level="ACTION")
    servo.ChangeDutyCycle(SERVO_TRIGGER)
    time.sleep(1.2)
    servo.ChangeDutyCycle(SERVO_NEUTRAL)
    time.sleep(0.8)
    servo.ChangeDutyCycle(0)  # stop PWM

# ================= MAVLINK =================

log_message("Connecting to Pixhawk...", also_print=False)
master = mavutil.mavlink_connection(PORT)
master.wait_heartbeat()
log_message("Pixhawk connected", level="OK", also_print=False)

def send_rtl():
    if(master.mav.command_long_send(
        master.target_system,
        master.target_component,
        mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH,
        0,
        0, 0, 0, 0, 0, 0, 0
    )):
        log_message("RTL command sent", level="ACTION")
    else:
        log_message("Failed to send RTL", level="ERROR")

# ================= CAMERA =================

log_message("Initializing camera...", also_print=False)
cap = cv2.VideoCapture(CAMERA_ID)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Reduce buffer to minimize latency

if not cap.isOpened():
    log_message("Failed to open camera", level="ERROR")
    GPIO.cleanup()
    exit(1)

actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
log_message(f"Camera ready: {actual_width}x{actual_height}", level="OK", also_print=False)

# pyzbar doesn't need initialization

# Thread-safe queues for parallel processing
frame_queue = Queue(maxsize=FRAME_QUEUE_SIZE)
result_queue = Queue()
windows_queue = Queue(maxsize=5)  # Queue for sending to Windows server

# Shared state
qr_count = 0
should_stop = False
detection_complete = False
session_id = f"drone_{int(time.time())}"

# Shared frame for Flask streaming
current_frame = None
frame_lock = threading.Lock()

# Shared QR code content
last_qr_content = None
qr_content_lock = threading.Lock()

# Stats
frames_sent_to_windows = 0
windows_send_errors = 0
frames_processed = 0

log_message("System initialized", also_print=False)

# ================= FLASK WEB SERVER =================

app = Flask(__name__)

@app.route('/video_feed')
def video_feed():
    """Stream video frames as MJPEG (for ngrok)"""
    def generate():
        while not should_stop and not detection_complete:
            with frame_lock:
                if current_frame is not None:
                    _, buffer = cv2.imencode('.jpg', current_frame)
                    frame_bytes = buffer.tobytes()
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n'
                           b'Content-Length: ' + str(len(frame_bytes)).encode() + b'\r\n\r\n'
                           + frame_bytes + b'\r\n')
            time.sleep(0.03)  # ~30 FPS
    
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/status')
def status():
    """Get current system status"""
    return {
        'qr_count': qr_count,
        'target_frames': QR_CONFIRM_FRAMES,
        'detection_complete': detection_complete,
        'frames_sent_to_windows': frames_sent_to_windows,
        'windows_errors': windows_send_errors
    }

@app.route('/health')
def health():
    """Health check endpoint"""
    return {'status': 'running', 'timestamp': time.time()}

@app.route('/qr_content')
def qr_content():
    """Get the last scanned QR code content"""
    with qr_content_lock:
        return {
            'qr_content': last_qr_content,
            'timestamp': time.time()
        }

log_message("Flask app configured", also_print=False)

# ================= CAPTURE PIPELINE =================

def capture_frames():
    """Continuously capture frames from camera - SINGLE SOURCE FOR ALL"""
    global should_stop, current_frame, frames_processed
    frame_id = 0
    
    while not should_stop:
        ret, frame = cap.read()
        if not ret:
            continue
        
        frame_id += 1
        frames_processed = frame_id
        
        # Update shared frame for Flask streaming (non-blocking)
        with frame_lock:
            current_frame = frame.copy()
        
        # Send to QR detection pipeline (with timeout to avoid blocking)
        try:
            frame_queue.put((frame_id, frame.copy()), timeout=0.1)
        except:
            pass  # Skip frame if queue is full
        
        # Send to Windows server pipeline
        if SEND_TO_WINDOWS:
            try:
                windows_queue.put((frame_id, frame.copy()), timeout=0.1)
            except:
                pass  # Skip frame if queue is full

# ================= QR DETECTION PIPELINE =================

def detect_qr_codes():
    """Process frames and detect QR codes"""
    global qr_count, should_stop, detection_complete
    
    while not should_stop:
        try:
            frame_id, frame = frame_queue.get(timeout=1)
        except:
            continue
        
        # Keep original color frame for display
        display_frame = frame.copy()
        
        # Use pyzbar to decode QR codes
        decoded_objects = decode(frame)
        
        # Extract text from pyzbar objects
        decoded_texts = [obj.data.decode('utf-8') for obj in decoded_objects]
        
        result = {
            'frame_id': frame_id,
            'frame': display_frame,
            'decoded_objects': decoded_texts
        }
        
        result_queue.put(result)

# ================= WINDOWS SERVER PIPELINE =================

def send_to_windows_server():
    """Send frames to Windows server API"""
    global frames_sent_to_windows, windows_send_errors
    
    session = requests.Session()  # Reuse connection for speed
    url = f"{WINDOWS_SERVER_URL}/api/stream/frame"
    
    while not should_stop:
        try:
            frame_id, frame = windows_queue.get(timeout=1)
            
            # Compress frame
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
            _, buffer = cv2.imencode('.jpg', frame, encode_param)
            jpeg_data = buffer.tobytes()
            
            # Send to server
            files = {'frame': ('frame.jpg', jpeg_data, 'image/jpeg')}
            data = {
                'session_id': session_id,
                'frame_num': frame_id,
                'timestamp': time.time()
            }
            
            try:
                response = session.post(url, files=files, data=data, timeout=2)
                
                if response.status_code == 200:
                    frames_sent_to_windows += 1
                else:
                    windows_send_errors += 1
                    
            except requests.exceptions.RequestException as e:
                windows_send_errors += 1
                if windows_send_errors % 100 == 1:
                    print(f"[WARN] Windows server send error: {e}")
            
            windows_queue.task_done()
            
        except:
            continue

# ================= FLASK SERVER THREAD =================

def run_flask():
    """Run Flask web server"""
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False, threaded=True, use_reloader=False)

# ================= STATS THREAD =================

def print_stats():
    """Log periodic statistics to file only"""
    while not should_stop:
        time.sleep(5)
        if SEND_TO_WINDOWS:
            log_message(f"QR: {qr_count}/{QR_CONFIRM_FRAMES} | Windows frames sent: {frames_sent_to_windows} | Errors: {windows_send_errors}", also_print=False, level="STATS")
        else:
            log_message(f"QR: {qr_count}/{QR_CONFIRM_FRAMES}", also_print=False, level="STATS")

# ================= MAIN CONTROL LOOP =================

def main():
    global should_stop, detection_complete, qr_count, last_qr_content, frames_processed
    
    # Print clean banner
    print("\n🚁 DRONE CONTROLLER v1.0")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    # Log all details to file
    log_message("="*70, also_print=False)
    log_message("UNIFIED DRONE CONTROLLER STARTUP", also_print=False)
    log_message("="*70, also_print=False)
    log_message(f"Mavlink: {PORT}", also_print=False)
    log_message(f"Servo GPIO: {SERVO_GPIO}", also_print=False)
    log_message(f"Camera: {actual_width}x{actual_height}", also_print=False)
    log_message(f"Flask streaming: http://{FLASK_HOST}:{FLASK_PORT}/video_feed", also_print=False)
    log_message(f"Status API: http://{FLASK_HOST}:{FLASK_PORT}/status", also_print=False)
    log_message(f"Log file: {LOG_FILE}", also_print=False)
    if SEND_TO_WINDOWS:
        log_message(f"Windows server: {WINDOWS_SERVER_URL}", also_print=False)
    log_message("="*70, also_print=False)
    
    # Show essential info to terminal
    log_message("Pixhawk connected", level="OK")
    log_message(f"Camera ready: {actual_width}x{actual_height}", level="OK")
    log_message(f"Flask server: http://{FLASK_HOST}:{FLASK_PORT}", level="OK")
    
    # Start capture thread (SINGLE camera feed for all)
    capture_thread = threading.Thread(target=capture_frames, daemon=True)
    capture_thread.start()
    log_message("Camera capture pipeline started", also_print=False)
    
    # Start QR detection threads
    detection_threads = []
    for i in range(NUM_DETECTION_THREADS):
        thread = threading.Thread(target=detect_qr_codes, daemon=True)
        thread.start()
        detection_threads.append(thread)
    log_message(f"QR detection pipeline started ({NUM_DETECTION_THREADS} threads)", also_print=False)
    
    # Start Windows server thread
    if SEND_TO_WINDOWS:
        windows_thread = threading.Thread(target=send_to_windows_server, daemon=True)
        windows_thread.start()
        log_message("Windows server pipeline started", also_print=False)
    
    # Start Flask web server
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    log_message("Flask web server started", also_print=False)
    
    # Start stats thread
    stats_thread = threading.Thread(target=print_stats, daemon=True)
    stats_thread.start()
    
    log_message("All systems operational", level="OK")
    print("")
    log_message("Scanning for QR codes...", level="INFO")
    print("")
    
    # Main processing loop
    while True:
        try:
            result = result_queue.get(timeout=1)
            frame = result['frame']
            decoded_objects = result['decoded_objects']
            
            if decoded_objects:
                for data in decoded_objects:
                    # data is already a string from pyzbar
                    
                    # Update the last scanned QR content
                    with qr_content_lock:
                        last_qr_content = data
                    log_message(f"QR CODE DETECTED: \"{data}\"", level="QR")
                    log_message(f"Raw data: {repr(data)}", also_print=False)
                    
                    if data.strip() == VALID_QR_TEXT:
                        qr_count += 1
                        log_message(f"Valid QR code detected ({qr_count}/{QR_CONFIRM_FRAMES} frames)", also_print=False)
                        
                        if qr_count >= QR_CONFIRM_FRAMES:
                            log_message(f"QR confirmed ({qr_count}/{QR_CONFIRM_FRAMES} frames)", level="OK")
                            detection_complete = True
                            should_stop = True
                            
                            trigger_servo()
                            send_rtl()
                            
                            break
                    else:
                        qr_count = 0
            
            # Show frame locally (only if not headless)
            if not HEADLESS_MODE:
                cv2.imshow("Unified Drone Controller", frame)
                
                if cv2.waitKey(1) & 0xFF == 27:
                    log_message("User stopped (ESC key)", also_print=False)
                    should_stop = True
                    break
            
            if detection_complete:
                break
        
        except KeyboardInterrupt:
            log_message("User stopped (Ctrl+C)", also_print=False)
            should_stop = True
            break
        except:
            continue
    
    # ================= CLEANUP =================
    
    log_message("Shutting down...", also_print=False)
    time.sleep(1)  # Give threads time to finish
    
    cap.release()
    if not HEADLESS_MODE:
        cv2.destroyAllWindows()
    servo.stop()
    GPIO.cleanup()
    
    # Print clean summary
    print("\n📊 SESSION SUMMARY:")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"   • QR codes scanned: {qr_count}")
    print(f"   • Frames processed: {frames_processed:,}")
    if SEND_TO_WINDOWS:
        print(f"   • Windows frames sent: {frames_sent_to_windows:,}")
        if windows_send_errors > 0:
            print(f"   • Windows errors: {windows_send_errors}")
    print(f"   • Log file: {LOG_FILE}")
    print("")
    
    # Write final details to log
    log_message("All systems stopped", also_print=False)
    log_message(f"Final stats - Windows frames sent: {frames_sent_to_windows}, Errors: {windows_send_errors}", also_print=False)
    
    with qr_content_lock:
        if last_qr_content:
            log_message(f"Final QR content: {last_qr_content}", also_print=False)
    
    log_message("Shutdown complete", level="OK")
    print("")

if __name__ == '__main__':
    main()
