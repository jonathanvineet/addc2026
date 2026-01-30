#!/usr/bin/env python3
"""
UNIFIED DRONE CONTROLLER
Combines QR detection, servo control, video streaming, and Windows server API communication
Uses ONE camera feed for all operations
"""

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
WINDOWS_SERVER_IP = "192.168.1.28"
WINDOWS_SERVER_PORT = 5000
WINDOWS_SERVER_URL = f'http://{WINDOWS_SERVER_IP}:{WINDOWS_SERVER_PORT}'
JPEG_QUALITY = 85
SEND_TO_WINDOWS = True  # Set to False to disable sending to Windows server

# =========================================

# ================= GPIO SETUP =================

GPIO.setmode(GPIO.BCM)
GPIO.setup(SERVO_GPIO, GPIO.OUT)

servo = GPIO.PWM(SERVO_GPIO, SERVO_FREQ)
servo.start(0)

def trigger_servo():
    print("[ACTION] Servo triggered")
    servo.ChangeDutyCycle(SERVO_TRIGGER)
    time.sleep(1.2)
    servo.ChangeDutyCycle(SERVO_NEUTRAL)
    time.sleep(0.8)
    servo.ChangeDutyCycle(0)  # stop PWM

# ================= MAVLINK =================

print("[INFO] Connecting to Pixhawk...")
master = mavutil.mavlink_connection(PORT)
master.wait_heartbeat()
print("[OK] Heartbeat received")

def send_rtl():
    if(master.mav.command_long_send(
        master.target_system,
        master.target_component,
        mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH,
        0,
        0, 0, 0, 0, 0, 0, 0
    )):
        print("[ACTION] RTL sent")
    else:
        print("[ERROR] Failed to send RTL")

# ================= CAMERA =================

print("[INFO] Initializing camera...")
cap = cv2.VideoCapture(CAMERA_ID)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Reduce buffer to minimize latency

if not cap.isOpened():
    raise RuntimeError("Failed to open camera")

actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
print(f"[OK] Camera ready: {actual_width}x{actual_height}")

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

# Stats
frames_sent_to_windows = 0
windows_send_errors = 0

print("[INFO] System initialized")

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

print("[INFO] Flask app configured")

# ================= CAPTURE PIPELINE =================

def capture_frames():
    """Continuously capture frames from camera - SINGLE SOURCE FOR ALL"""
    global should_stop
    frame_id = 0
    
    while not should_stop:
        ret, frame = cap.read()
        if not ret:
            continue
        
        frame_id += 1
        
        # Update shared frame for Flask streaming (non-blocking)
        with frame_lock:
            current_frame = frame.copy()
        
        # Send to QR detection pipeline
        if not frame_queue.full():
            frame_queue.put((frame_id, frame.copy()))
        
        # Send to Windows server pipeline
        if SEND_TO_WINDOWS and not windows_queue.full():
            windows_queue.put((frame_id, frame.copy()))

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
    """Print periodic statistics"""
    while not should_stop:
        time.sleep(5)
        if SEND_TO_WINDOWS:
            print(f"[STATS] QR: {qr_count}/{QR_CONFIRM_FRAMES} | Windows frames sent: {frames_sent_to_windows} | Errors: {windows_send_errors}")
        else:
            print(f"[STATS] QR: {qr_count}/{QR_CONFIRM_FRAMES}")

# ================= MAIN CONTROL LOOP =================

def main():
    global should_stop, detection_complete, qr_count
    
    print("\n" + "="*70)
    print("🚁 UNIFIED DRONE CONTROLLER")
    print("="*70)
    print(f"📡 Mavlink: {PORT}")
    print(f"🔌 Servo GPIO: {SERVO_GPIO}")
    print(f"📹 Camera: {actual_width}x{actual_height}")
    print(f"🌐 Flask streaming: http://{FLASK_HOST}:{FLASK_PORT}/video_feed")
    print(f"📊 Status API: http://{FLASK_HOST}:{FLASK_PORT}/status")
    if SEND_TO_WINDOWS:
        print(f"💻 Windows server: {WINDOWS_SERVER_URL}")
    print("="*70 + "\n")
    
    # Start capture thread (SINGLE camera feed for all)
    capture_thread = threading.Thread(target=capture_frames, daemon=True)
    capture_thread.start()
    print("[OK] Camera capture pipeline started")
    
    # Start QR detection threads
    detection_threads = []
    for i in range(NUM_DETECTION_THREADS):
        thread = threading.Thread(target=detect_qr_codes, daemon=True)
        thread.start()
        detection_threads.append(thread)
    print(f"[OK] QR detection pipeline started ({NUM_DETECTION_THREADS} threads)")
    
    # Start Windows server thread
    if SEND_TO_WINDOWS:
        windows_thread = threading.Thread(target=send_to_windows_server, daemon=True)
        windows_thread.start()
        print("[OK] Windows server pipeline started")
    
    # Start Flask web server
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("[OK] Flask web server started")
    
    # Start stats thread
    stats_thread = threading.Thread(target=print_stats, daemon=True)
    stats_thread.start()
    
    print("\n[INFO] All systems operational! Waiting for QR code...\n")
    
    # Main processing loop
    while True:
        try:
            result = result_queue.get(timeout=1)
            frame = result['frame']
            decoded_objects = result['decoded_objects']
            
            if decoded_objects:
                for data in decoded_objects:
                    # data is already a string from pyzbar
                    
                    if data.strip() == VALID_QR_TEXT:
                        qr_count += 1
                        print(f"[DEBUG] Valid QR ({qr_count}/{QR_CONFIRM_FRAMES})")
                        
                        if qr_count >= QR_CONFIRM_FRAMES:
                            print("\n[OK] ✅ QR CONFIRMED!")
                            detection_complete = True
                            should_stop = True
                            
                            trigger_servo()
                            send_rtl()
                            
                            break
                    else:
                        qr_count = 0
            
            # Show frame locally (optional, can disable on headless)
            cv2.imshow("Unified Drone Controller", frame)
            
            if cv2.waitKey(1) & 0xFF == 27:
                print("\n[ABORT] User stopped (ESC key)")
                should_stop = True
                break
            
            if detection_complete:
                break
        
        except KeyboardInterrupt:
            print("\n[ABORT] User stopped (Ctrl+C)")
            should_stop = True
            break
        except:
            continue
    
    # ================= CLEANUP =================
    
    print("\n[INFO] Shutting down...")
    time.sleep(1)  # Give threads time to finish
    
    cap.release()
    cv2.destroyAllWindows()
    servo.stop()
    GPIO.cleanup()
    
    print("[DONE] ✅ All systems stopped")
    print(f"[STATS] Final - Windows frames sent: {frames_sent_to_windows}, Errors: {windows_send_errors}\n")

if __name__ == '__main__':
    main()
