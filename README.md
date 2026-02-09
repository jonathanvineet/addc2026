# addc2026

Unified drone controller that combines camera capture, QR detection, servo actuation, Pixhawk RTL, and video streaming. It uses a single camera feed for all pipelines and can optionally forward frames to a Windows server API.

## What it does

- Captures frames from one camera and fans them out to:
	- QR detection (pyzbar)
	- MJPEG streaming over Flask (`/video_feed`)
	- Optional Windows server upload (`/api/stream/frame`)
- Confirms a valid QR code across multiple frames, then:
	- Triggers a servo
	- Sends Pixhawk Return-To-Launch (RTL) via MAVLink

## Requirements

- Raspberry Pi (or Linux host) with a camera
- Pixhawk connected over USB serial (default `/dev/ttyACM0`)
- Python 3
- System libraries for OpenCV and zbar (for `pyzbar`)

Python packages used:

- `pymavlink`
- `opencv-python`
- `pyzbar`
- `flask`
- `requests`
- `numpy`
- `RPi.GPIO` (Pi only)

## Quick start

1. Edit configuration constants in [unified_drone.py](unified_drone.py) as needed.
2. Run:

```bash
python3 unified_drone.py
```

## Configuration

Key settings (edit in [unified_drone.py](unified_drone.py)):

- MAVLink serial port: `PORT`
- QR confirmation: `VALID_QR_TEXT`, `QR_CONFIRM_FRAMES`
- Servo: `SERVO_GPIO`, `SERVO_NEUTRAL`, `SERVO_TRIGGER`
- Camera: `CAMERA_ID`, `FRAME_WIDTH`, `FRAME_HEIGHT`, `CAMERA_FPS`
- Streaming: `FLASK_HOST`, `FLASK_PORT`
- Windows server: `WINDOWS_SERVER_URL`, `SEND_TO_WINDOWS`
- Headless mode: `HEADLESS_MODE` (disable local GUI)

## HTTP endpoints

- `GET /video_feed` - MJPEG stream
- `GET /status` - JSON status (QR count, frames sent, errors)
- `GET /health` - health check
- `GET /qr_content` - last decoded QR content

## Notes

- QR confirmation resets to 0 on any non-matching code.
- On confirmation, the program triggers the servo and sends RTL, then exits after cleanup.
- Logs are written to a timestamped file (e.g., `drone_log_<timestamp>.txt`).

## Safety

Test with props removed and on a bench before any flight. Servo actuation and RTL are real actions.