#!/usr/bin/env python3
"""
Test each import individually to find which one causes "Illegal instruction"
Run this on your Raspberry Pi
"""

import sys

print(f"Python version: {sys.version}")
print("=" * 60)

imports_to_test = [
    ("pymavlink", "from pymavlink import mavutil"),
    ("cv2", "import cv2"),
    ("time", "import time"),
    ("RPi.GPIO", "import RPi.GPIO as GPIO"),
    ("qreader", "from qreader import QReader"),
    ("threading", "import threading"),
    ("queue", "from queue import Queue"),
    ("numpy", "import numpy as np"),
    ("flask", "from flask import Flask, Response"),
    ("requests", "import requests"),
    ("io", "import io"),
]

for name, import_cmd in imports_to_test:
    try:
        print(f"Testing {name:15s}...", end=" ", flush=True)
        exec(import_cmd)
        print("✅ OK")
    except Exception as e:
        print(f"❌ FAILED: {e}")
        print(f"   Import command: {import_cmd}")

print("=" * 60)
print("Test complete!")
