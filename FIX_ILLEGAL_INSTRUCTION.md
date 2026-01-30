# Fix for "Illegal instruction" Error on Raspberry Pi

## Problem
The error occurs because NumPy, OpenCV, or other scientific libraries installed via `pip` were compiled for x86 CPU instructions that don't exist on ARM processors (Raspberry Pi).

## Solution - Run on your Raspberry Pi:

### Method 1: Quick Fix (Recommended)
```bash
# Run the fix script
bash fix_rpi_illegal_instruction.sh
```

### Method 2: Manual Fix

```bash
# 1. Identify the problematic library first
python3 test_imports.py

# 2. Uninstall pip versions
pip3 uninstall -y numpy opencv-python opencv-contrib-python

# 3. Install ARM-optimized versions from apt
sudo apt-get update
sudo apt-get install -y python3-opencv python3-numpy

# 4. Install other dependencies
pip3 install pymavlink qreader flask requests RPi.GPIO
```

### Method 3: Alternative - Use piwheels (ARM wheels)

If you prefer pip, use piwheels (pre-compiled for Raspberry Pi):

```bash
# Configure pip to use piwheels
echo "[global]" > ~/.pip/pip.conf
echo "extra-index-url=https://www.piwheels.org/simple" >> ~/.pip/pip.conf

# Then reinstall
pip3 install --upgrade numpy opencv-python
```

## Verify the Fix

```bash
# Test imports individually
python3 test_imports.py

# Run the main program
python3 unified_drone.py
```

## Most Likely Culprits

1. **NumPy** - Use: `sudo apt-get install python3-numpy`
2. **OpenCV** - Use: `sudo apt-get install python3-opencv`
3. **qreader** - May depend on wrong NumPy/OpenCV

## Alternative: Lighter QR Detection

If qreader still causes issues, you can use pyzbar instead:

```python
# Install
sudo apt-get install libzbar0
pip3 install pyzbar

# Replace in code:
from pyzbar.pyzbar import decode

# In detect_qr_codes():
decoded_objects = decode(frame)
for obj in decoded_objects:
    data = obj.data.decode('utf-8')
```

## Notes

- **NEVER** use pip to install numpy/opencv on RPi - always use apt
- The apt versions are optimized for ARM architecture
- This issue is common on RPi 3/4/Zero models
