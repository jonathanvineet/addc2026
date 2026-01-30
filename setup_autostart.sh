#!/bin/bash
# Setup script for Unified Drone Controller Auto-Start
# Run this once: chmod +x setup_autostart.sh && ./setup_autostart.sh

set -e  # Exit on error

echo "🚁 UNIFIED DRONE CONTROLLER - AUTO-START SETUP"
echo "=============================================="
echo ""

# 1. Make script executable
echo "✓ Making unified_drone.py executable..."
chmod +x unified_drone.py
ls -l unified_drone.py | grep rwx && echo "  Success: Execute permission set" || echo "  Warning: Check permissions"

# 2. Add user to video group (for camera access)
echo ""
echo "✓ Adding user to video group (for camera access)..."
sudo usermod -aG video $USER
echo "  Success: Added to video group (logout/login to apply)"

# 3. Copy systemd service file
echo ""
echo "✓ Installing systemd service..."
sudo cp unified_drone.service /etc/systemd/system/unified_drone.service
sudo chmod 644 /etc/systemd/system/unified_drone.service
echo "  Success: Service file installed"

# 4. Reload systemd and enable service
echo ""
echo "✓ Enabling auto-start on boot..."
sudo systemctl daemon-reload
sudo systemctl enable unified_drone.service
echo "  Success: Service enabled"

# 5. Create log files directory
echo ""
echo "✓ Preparing log files..."
touch unified_drone_stdout.log
touch unified_drone_stderr.log
chmod 666 unified_drone_stdout.log unified_drone_stderr.log
echo "  Success: Log files ready"

echo ""
echo "=============================================="
echo "✅ SETUP COMPLETE!"
echo "=============================================="
echo ""
echo "📋 NEXT STEPS:"
echo ""
echo "1. TEST NOW (without rebooting):"
echo "   sudo systemctl start unified_drone.service"
echo "   sudo systemctl status unified_drone.service"
echo ""
echo "2. VIEW LOGS:"
echo "   tail -f ~/addc2026/unified_drone_stdout.log"
echo "   tail -f ~/addc2026/unified_drone_stderr.log"
echo ""
echo "3. STOP SERVICE:"
echo "   sudo systemctl stop unified_drone.service"
echo ""
echo "4. REBOOT TEST:"
echo "   sudo reboot"
echo "   (After reboot, check: sudo systemctl status unified_drone.service)"
echo ""
echo "5. DISABLE AUTO-START (if needed):"
echo "   sudo systemctl disable unified_drone.service"
echo ""
echo "🎯 Your drone will now start automatically on boot!"
echo ""
