#!/usr/bin/env python3
"""
HIGH-PERFORMANCE RPi Camera Streaming Client
Captures frames and streams to ground station with maximum efficiency
"""

import requests
import cv2
import time
import numpy as np
from io import BytesIO
from threading import Thread, Lock
import queue
import sys

# Load configuration
try:
    from streaming_config import *
except ImportError:
    print("⚠️ streaming_config.py not found, using defaults")
    GROUND_STATION_IP = "192.168.1.28"
    GROUND_STATION_PORT = 5000
    FRAME_WIDTH = 1280
    FRAME_HEIGHT = 720
    CAMERA_FPS = 30
    JPEG_QUALITY = 85
    SKIP_FRAMES = 2
    BUFFER_SIZE = 5

# ============================================================================
# HIGH-PERFORMANCE CONFIGURATION
# ============================================================================

CONFIG = {
    # Ground station server
    'SERVER_URL': f'http://{GROUND_STATION_IP}:{GROUND_STATION_PORT}',
    
    # Camera settings (optimize for speed)
    'CAMERA_ID': 0,  # 0 for USB webcam, or use '/dev/video0' for RPi camera
    'FRAME_WIDTH': FRAME_WIDTH,
    'FRAME_HEIGHT': FRAME_HEIGHT,
    'FPS': CAMERA_FPS,
    
    # Compression settings (optimized for speed/quality balance)
    'JPEG_QUALITY': JPEG_QUALITY,  # 85 is sweet spot for speed/quality
    
    # Streaming settings
    'BUFFER_SIZE': BUFFER_SIZE,  # Small buffer for low latency
    'SKIP_FRAMES': SKIP_FRAMES,  # Send every Nth frame (0=all, 1=half, 2=third)
    
    # Session settings
    'SESSION_NAME': 'drone_live',
}


# ============================================================================
# HIGH-SPEED FRAME CAPTURE & COMPRESSION
# ============================================================================

class FastFrameStreamer:
    """Multi-threaded frame capture and streaming for maximum performance"""
    
    def __init__(self):
        self.frame_queue = queue.Queue(maxsize=CONFIG['BUFFER_SIZE'])
        self.capture = None
        self.session_id = f"{CONFIG['SESSION_NAME']}_{int(time.time())}"
        self.frame_count = 0
        self.sent_count = 0
        self.running = False
        self.stats_lock = Lock()
        
        # Performance metrics
        self.capture_fps = 0
        self.send_fps = 0
        self.last_stats_time = time.time()
        
    def init_camera(self):
        """Initialize camera with optimized settings"""
        print("🎥 Initializing camera...")
        
        # Try multiple methods to open camera
        camera_methods = [
            # Method 1: Direct V4L2 (best for Linux/RPi)
            (CONFIG['CAMERA_ID'], cv2.CAP_V4L2),
            # Method 2: Auto-detect backend
            (CONFIG['CAMERA_ID'], cv2.CAP_ANY),
            # Method 3: Try different indices with V4L2
            (0, cv2.CAP_V4L2),
            (1, cv2.CAP_V4L2),
            # Method 4: Try different indices with auto-detect
            (0, cv2.CAP_ANY),
            (1, cv2.CAP_ANY),
        ]
        
        self.capture = None
        for cam_id, backend in camera_methods:
            try:
                print(f"   Trying camera {cam_id} with backend {backend}...")
                cap = cv2.VideoCapture(cam_id, backend)
                
                if cap.isOpened():
                    # Test if we can actually read a frame
                    ret, test_frame = cap.read()
                    if ret and test_frame is not None:
                        self.capture = cap
                        print(f"   ✅ Camera opened successfully!")
                        break
                    else:
                        cap.release()
                else:
                    cap.release()
            except Exception as e:
                print(f"   ❌ Failed: {e}")
                continue
        
        if self.capture is None or not self.capture.isOpened():
            print("\n❌ Could not open camera!")
            print("\n💡 Troubleshooting:")
            print("   1. Check connected cameras: ls /dev/video*")
            print("   2. Check permissions: sudo usermod -a -G video $USER")
            print("   3. For RPi Camera Module: Enable in raspi-config")
            print("   4. Try: sudo modprobe bcm2835-v4l2")
            print("   5. Edit streaming_config.py to set CAMERA_ID")
            raise RuntimeError("Failed to open camera")
        
        # Set camera properties for maximum performance
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, CONFIG['FRAME_WIDTH'])
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, CONFIG['FRAME_HEIGHT'])
        self.capture.set(cv2.CAP_PROP_FPS, CONFIG['FPS'])
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimize buffer for low latency
        
        # Verify actual settings
        actual_width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = int(self.capture.get(cv2.CAP_PROP_FPS))
        
        # Validate we got reasonable values
        if actual_width == 0 or actual_height == 0:
            print("⚠️  Warning: Could not set resolution, using camera defaults")
            # Try to read a frame to get actual resolution
            ret, frame = self.capture.read()
            if ret and frame is not None:
                actual_height, actual_width = frame.shape[:2]
                print(f"   Detected resolution: {actual_width}x{actual_height}")
        
        print(f"✅ Camera ready: {actual_width}x{actual_height} @ {actual_fps} FPS")
    
    def capture_thread(self):
        """Capture frames continuously (runs in separate thread)"""
        capture_count = 0
        last_time = time.time()
        
        while self.running:
            ret, frame = self.capture.read()
            
            if not ret:
                print("⚠️ Failed to capture frame")
                time.sleep(0.01)
                continue
            
            capture_count += 1
            
            # Skip frames if configured (0=send all, 1=skip 1, 2=skip 2, etc.)
            if SKIP_FRAMES > 0 and capture_count % (SKIP_FRAMES + 1) != 0:
                continue
            
            # Add to queue (non-blocking, drop if full)
            try:
                self.frame_queue.put_nowait((capture_count, frame))
                self.frame_count = capture_count
            except queue.Full:
                pass  # Drop frame if queue is full (keeps latency low)
            
            # Update FPS
            if capture_count % 30 == 0:
                now = time.time()
                self.capture_fps = 30 / (now - last_time)
                last_time = now
    
    def compress_frame(self, frame):
        """Fast JPEG compression"""
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), CONFIG['JPEG_QUALITY']]
        _, buffer = cv2.imencode('.jpg', frame, encode_param)
        return buffer.tobytes()
    
    def send_thread(self):
        """Send frames to server (runs in separate thread)"""
        session = requests.Session()  # Reuse connection for speed
        url = f"{CONFIG['SERVER_URL']}/api/stream/frame"
        
        sent_count = 0
        last_time = time.time()
        
        while self.running:
            try:
                # Get frame from queue (with timeout)
                frame_num, frame = self.frame_queue.get(timeout=0.1)
                
                # Compress frame (FAST!)
                jpeg_data = self.compress_frame(frame)
                
                # Send to server
                files = {'frame': ('frame.jpg', jpeg_data, 'image/jpeg')}
                data = {
                    'session_id': self.session_id,
                    'frame_num': frame_num,
                    'timestamp': time.time()
                }
                
                try:
                    response = session.post(url, files=files, data=data, timeout=2)
                    
                    if response.status_code == 200:
                        sent_count += 1
                        self.sent_count = sent_count
                        
                        # Update FPS
                        if sent_count % 10 == 0:
                            now = time.time()
                            self.send_fps = 10 / (now - last_time)
                            last_time = now
                    else:
                        print(f"❌ Server error: {response.status_code}")
                        
                except requests.exceptions.RequestException as e:
                    print(f"❌ Send error: {e}")
                
                self.frame_queue.task_done()
                
            except queue.Empty:
                continue
    
    def stats_thread(self):
        """Display performance statistics"""
        while self.running:
            time.sleep(2)
            
            print(f"\r📊 Captured: {self.frame_count} | Sent: {self.sent_count} | "
                  f"Capture FPS: {self.capture_fps:.1f} | Send FPS: {self.send_fps:.1f} | "
                  f"Queue: {self.frame_queue.qsize()}", end='', flush=True)
    
    def start(self):
        """Start streaming"""
        print(f"\n🚀 Starting high-performance stream: {self.session_id}\n")
        
        self.init_camera()
        self.running = True
        
        # Start threads
        Thread(target=self.capture_thread, daemon=True).start()
        Thread(target=self.send_thread, daemon=True).start()
        Thread(target=self.stats_thread, daemon=True).start()
        
        print("✅ Streaming active! Press Ctrl+C to stop.\n")
        
        try:
            # Keep main thread alive
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\n🛑 Stopping stream...")
            self.stop()
    
    def stop(self):
        """Stop streaming"""
        self.running = False
        
        if self.capture:
            self.capture.release()
        
        print(f"\n✅ Stream stopped. Total frames sent: {self.sent_count}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main entry point"""
    print("=" * 70)
    print("🚁 DRONE HIGH-PERFORMANCE FRAME STREAMING")
    print("=" * 70)
    print(f"📡 Ground Station: {CONFIG['SERVER_URL']}")
    print(f"📹 Resolution: {FRAME_WIDTH}x{FRAME_HEIGHT} @ {CAMERA_FPS} FPS")
    print(f"🎯 JPEG Quality: {JPEG_QUALITY}%")
    print(f"⚡ Frame Mode: Send every {SKIP_FRAMES + 1}{'st' if SKIP_FRAMES == 0 else 'nd' if SKIP_FRAMES == 1 else 'rd' if SKIP_FRAMES == 2 else 'th'} frame")
    print(f"💾 Buffer Size: {BUFFER_SIZE} frames")
    print("=" * 70)
    print()
    
    streamer = FastFrameStreamer()
    streamer.start()


if __name__ == '__main__':
    main()
