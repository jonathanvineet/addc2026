# RASPBERRY PI AUTO-START SETUP GUIDE

## ✅ Your code is now HEADLESS-SAFE!

**Changes made to `unified_drone.py`:**
- Added `HEADLESS_MODE = True` config (line ~65)
- cv2.imshow() only runs when `HEADLESS_MODE = False`
- No display crashes on boot ✅

---

## 🚀 ONE-COMMAND SETUP

```bash
cd ~/addc2026
chmod +x setup_autostart.sh
./setup_autostart.sh
```

**This script does everything:**
1. ✓ Makes script executable
2. ✓ Adds user to video group
3. ✓ Installs systemd service
4. ✓ Enables auto-start
5. ✓ Creates log files

---

## 🧪 TEST WITHOUT REBOOTING

```bash
# Start the service
sudo systemctl start unified_drone.service

# Check status
sudo systemctl status unified_drone.service

# Watch logs
tail -f ~/addc2026/unified_drone_stdout.log
```

You should see:
```
Active: active (running)
```

---

## 📊 MONITORING & DEBUGGING

### View live logs:
```bash
# Main output
tail -f ~/addc2026/unified_drone_stdout.log

# Errors only
tail -f ~/addc2026/unified_drone_stderr.log

# Drone log (with QR codes!)
tail -f ~/addc2026/drone_log_*.txt
```

### Check service status:
```bash
sudo systemctl status unified_drone.service
```

### Stop the service:
```bash
sudo systemctl stop unified_drone.service
```

---

## 🔁 REBOOT TEST (Final Step)

```bash
sudo reboot
```

After reboot, SSH back in and check:
```bash
sudo systemctl status unified_drone.service
```

**If you see `Active: active (running)` → 🎯 SUCCESS!**

---

## 🛠️ MANUAL SETUP (if you prefer)

If you want to do it manually instead of using the script:

```bash
cd ~/addc2026

# 1. Make executable
chmod +x unified_drone.py

# 2. Add to video group
sudo usermod -aG video pi

# 3. Install service
sudo cp unified_drone.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable unified_drone.service

# 4. Test it
sudo systemctl start unified_drone.service
sudo systemctl status unified_drone.service
```

---

## ⚙️ CONFIGURATION OPTIONS

### Headless Mode (for boot):
```python
HEADLESS_MODE = True  # No display window
```

### Testing Mode (with monitor):
```python
HEADLESS_MODE = False  # Shows cv2.imshow() window
```

---

## 🔧 TROUBLESHOOTING

### Pixhawk not found on boot?
The service auto-restarts every 5 seconds until Pixhawk connects.

Or add a delay:
```bash
# Edit service file
sudo nano /etc/systemd/system/unified_drone.service

# Add this line under [Service]:
ExecStartPre=/bin/sleep 10
```

### Camera permission denied?
```bash
sudo usermod -aG video pi
# Logout and login again
```

### Service won't start?
```bash
# Check detailed errors
journalctl -u unified_drone.service -n 50
```

---

## 📋 USEFUL COMMANDS

| Command | Purpose |
|---------|---------|
| `sudo systemctl start unified_drone.service` | Start now |
| `sudo systemctl stop unified_drone.service` | Stop service |
| `sudo systemctl restart unified_drone.service` | Restart service |
| `sudo systemctl status unified_drone.service` | Check status |
| `sudo systemctl enable unified_drone.service` | Enable auto-start |
| `sudo systemctl disable unified_drone.service` | Disable auto-start |
| `journalctl -u unified_drone.service -f` | Live system logs |

---

## ✅ ALL SET!

Your drone controller will now:
- ✅ Start automatically on boot
- ✅ Restart if it crashes
- ✅ Run headless (no monitor needed)
- ✅ Log everything to files
- ✅ Work with Pixhawk, camera, servo, Flask, ngrok

**Ready for deployment! 🚁**
