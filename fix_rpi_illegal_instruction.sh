#!/bin/bash
# FIX FOR "Illegal instruction" ERROR ON RASPBERRY PI
# This script reinstalls problematic packages using proper ARM builds

echo "========================================="
echo "Raspberry Pi - Fixing Illegal Instruction"
echo "========================================="
echo ""

# Update system
echo "[1/5] Updating system packages..."
sudo apt-get update

# Install OpenCV via apt (ARM optimized)
echo "[2/5] Installing OpenCV via apt (ARM build)..."
sudo apt-get install -y python3-opencv

# Uninstall pip versions of problematic packages
echo "[3/5] Removing pip-installed numpy and opencv-python..."
pip3 uninstall -y numpy opencv-python opencv-contrib-python

# Install NumPy via apt (ARM optimized)
echo "[4/5] Installing NumPy via apt (ARM build)..."
sudo apt-get install -y python3-numpy

# Reinstall other dependencies via pip (safe ones)
echo "[5/5] Installing remaining dependencies..."
sudo apt-get install -y libzbar0
pip3 install pymavlink pyzbar flask requests RPi.GPIO

echo ""
echo "========================================="
echo "✅ Installation complete!"
echo "========================================="
echo ""
echo "Now test with: python3 test_imports.py"
echo "Then run: python3 unified_drone.py"
