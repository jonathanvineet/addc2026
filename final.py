from pymavlink import mavutil
import cv2
import time
import RPi.GPIO as GPIO
from qreader import QReader
import threading
from queue import Queue
import numpy as np
from flask import Flask, Response
import io

# ================= CONFIG =================

PORT = '/dev/ttyACM0'

VALID_QR_TEXT = "SCANNED"
QR_CONFIRM_FRAMES = 8

SERVO_GPIO = 18        # BCM pin
SERVO_FREQ = 50        # 50Hz

# Adjust these for your servo
SERVO_NEUTRAL = 2.5
SERVO_TRIGGER = 7.5

# Parallel processing config
FRAME_QUEUE_SIZE = 10
NUM_DETECTION_THREADS = 2

# Web server config
FLASK_HOST = '0.0.0.0'
FLASK_PORT = 5000

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

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Reduce buffer to minimize latency

qreader = QReader()

# Thread-safe queues for parallel processing
frame_queue = Queue(maxsize=FRAME_QUEUE_SIZE)
result_queue = Queue()

# Shared state
qr_count = 0
should_stop = False
detection_complete = False

print("[INFO] QR scanning started")

# ================= FLASK WEB SERVER =================

app = Flask(__name__)

# Shared frame for streaming
current_frame = None
frame_lock = threading.Lock()

@app.route('/video_feed')
def video_feed():
    """Stream video frames as MJPEG"""
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
    """Get current QR detection status"""
    return {
        'qr_count': qr_count,
        'target_frames': QR_CONFIRM_FRAMES,
        'detection_complete': detection_complete
    }

print("[INFO] Flask app configured")

# ================= CAPTURE PIPELINE =================

def capture_frames():
    """Continuously capture frames from camera"""
    global should_stop
    frame_id = 0
    while not should_stop:
        ret, frame = cap.read()
        if not ret:
            continue
        
        # Skip frames if queue is full to maintain real-time performance
        if not frame_queue.full():
            frame_queue.put((frame_id, frame))
            frame_id += 1

# ================= DETECTION PIPELINE =================

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
        
        decoded_objects = qreader.detect_and_decode(frame)
        
        result = {
            'frame_id': frame_id,
            'frame': display_frame,  # Use original color frame
            'decoded_objects': decoded_objects
        }
        
        result_queue.put(result)

# ================= WEB SERVER THREAD =================

def run_flask():
    """Run Flask web server"""
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False, threaded=True)

# ================= MAIN CONTROL LOOP =================

# Start capture thread
capture_thread = threading.Thread(target=capture_frames, daemon=True)
capture_thread.start()

# Start detection threads
detection_threads = []
for i in range(NUM_DETECTION_THREADS):
    thread = threading.Thread(target=detect_qr_codes, daemon=True)
    thread.start()
    detection_threads.append(thread)

# Start Flask web server
flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

print("[INFO] Parallel pipelines started")
print(f"[INFO] Video stream available at http://0.0.0.0:{FLASK_PORT}/video_feed")
print(f"[INFO] Status available at http://0.0.0.0:{FLASK_PORT}/status")

while True:
    try:
        result = result_queue.get(timeout=1)
        frame = result['frame']
        decoded_objects = result['decoded_objects']

        # Update current frame for streaming
        with frame_lock:
            current_frame = frame.copy()

        if decoded_objects:
            for obj in decoded_objects:
                data = obj

                if data.strip() == VALID_QR_TEXT:
                    qr_count += 1
                    print(f"[DEBUG] Valid QR ({qr_count}/{QR_CONFIRM_FRAMES})")

                    if qr_count >= QR_CONFIRM_FRAMES:
                        print("[OK] QR CONFIRMED")
                        detection_complete = True
                        should_stop = True

                        trigger_servo()
                        send_rtl()

                        break
                else:
                    qr_count = 0

        cv2.imshow("QR Scanner", frame)

        if cv2.waitKey(1) & 0xFF == 27:
            print("[ABORT] User stopped")
            should_stop = True
            break
        
        if detection_complete:
            break

    except:
        continue

# ================= CLEANUP =================

cap.release()
cv2.destroyAllWindows()
servo.stop()
GPIO.cleanup()

print("[DONE] Process completed")
