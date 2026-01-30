# Installing pyzbar on Raspberry Pi

## The Problem
`qreader` causes "Illegal instruction" on Raspberry Pi ARM processors.

## The Solution
Replace with `pyzbar` - a lightweight, ARM-compatible QR/barcode scanner.

## Installation (Run on your Raspberry Pi)

```bash
# Install libzbar system library
sudo apt-get update
sudo apt-get install -y libzbar0

# Install pyzbar Python wrapper
pip3 install pyzbar

# Test it works
python3 test_imports.py
```

## Quick Install (All-in-one)

```bash
bash fix_rpi_illegal_instruction.sh
```

## Verify Installation

```bash
# Test imports
python3 test_imports.py

# Run the drone controller
python3 unified_drone.py
```

## What Changed

- **Before:** `from qreader import QReader` (heavy, x86-optimized)
- **After:** `from pyzbar.pyzbar import decode` (lightweight, ARM-compatible)

## pyzbar Advantages

✅ Works on Raspberry Pi (ARM)  
✅ Lightweight (<1MB)  
✅ Fast QR/barcode detection  
✅ Actively maintained  
✅ No deep learning dependencies  

## Code Changes Summary

The unified_drone.py has been updated to use pyzbar. The QR detection logic remains the same - it will still:
- Detect "SCANNED" QR code
- Count 8 consecutive frames
- Trigger servo and RTL when confirmed
