from pymavlink import mavutil
import cv2
import time
import RPi.GPIO as GPIO
from qreader import QReader

# ================= CONFIG =================

PORT = '/dev/ttyACM0'

VALID_QR_TEXT = "SCANNED"
QR_CONFIRM_FRAMES = 8

SERVO_GPIO = 18        # BCM pin
SERVO_FREQ = 50        # 50Hz

# Adjust these for your servo
SERVO_NEUTRAL = 2.5
SERVO_TRIGGER = 7.5

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
qreader = QReader()

qr_count = 0

print("[INFO] QR scanning started")

# ================= MAIN LOOP =================

while True:
    ret, frame = cap.read()
    if not ret:
        continue

    decoded_objects = qreader.detect_and_decode(frame)

    if decoded_objects:
        for obj in decoded_objects:
            data = obj
            bbox = None  # qreader doesn't return bbox like cv2

            if data.strip() == VALID_QR_TEXT:
                qr_count += 1
                print(f"[DEBUG] Valid QR ({qr_count}/{QR_CONFIRM_FRAMES})")

                if qr_count >= QR_CONFIRM_FRAMES:
                    print("[OK] QR CONFIRMED")

                    trigger_servo()
                    send_rtl()

                    break
            else:
                qr_count = 0

    cv2.imshow("QR Scanner", frame)

    if cv2.waitKey(1) & 0xFF == 27:
        print("[ABORT] User stopped")
        break

    time.sleep(0.05)

# ================= CLEANUP =================

cap.release()
cv2.destroyAllWindows()
servo.stop()
GPIO.cleanup()

print("[DONE] Process completed")
