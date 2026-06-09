#!/usr/bin/env bash
# deploy.sh — copy DVR files onto a mounted RPi SD card
# Usage: sudo bash deploy.sh /path/to/mounted/boot /path/to/mounted/rootfs
#
# Example after mounting SD card on Linux:
#   sudo mount /dev/sdb1 /mnt/boot
#   sudo mount /dev/sdb2 /mnt/root
#   sudo bash deploy.sh /mnt/boot /mnt/root
set -euo pipefail

BOOT="${1:-/mnt/boot}"
ROOT="${2:-/mnt/root}"
REPO="$(cd "$(dirname "$0")" && pwd)"

echo "=== DVR deploy ==="
echo "  Boot: $BOOT"
echo "  Root: $ROOT"

if [ ! -d "$BOOT" ] || [ ! -d "$ROOT" ]; then
    echo "ERROR: mount points not found"; exit 1
fi

# ── /boot files ──────────────────────────────────────────────────────────────
echo "--- copying boot config ---"
cp "$REPO/setup/config.txt" "$BOOT/config.txt"

# Preserve PARTUUID in cmdline.txt — read it from the existing cmdline
EXISTING_PARTUUID=$(grep -oP 'root=PARTUUID=\K[^\s]+' "$BOOT/cmdline.txt" 2>/dev/null || echo "CHANGE_ME")
sed "s/CHANGE_ME/$EXISTING_PARTUUID/" "$REPO/setup/cmdline.txt" > "$BOOT/cmdline.txt"

# Seed WiFi (user should edit this file first)
if [ -f "$REPO/setup/wpa_supplicant.conf" ]; then
    cp "$REPO/setup/wpa_supplicant.conf" "$BOOT/wpa_supplicant.conf"
    echo "  [!] Edit $BOOT/wpa_supplicant.conf with your WiFi credentials before booting"
fi

# Enable SSH headless setup
touch "$BOOT/ssh"
echo "  SSH enabled (touch /boot/ssh)"

# Copy install + readonly scripts to /boot for easy access after first boot
cp "$REPO/setup/install.sh"  "$BOOT/install.sh"
cp "$REPO/setup/readonly.sh" "$BOOT/readonly.sh"
cp "$REPO/setup/asound.conf" "$BOOT/asound.conf"
cp "$REPO/setup/tc358743.sh" "$BOOT/tc358743.sh"
[ -f "$REPO/setup/tc358743-1080p25.edid" ] && \
    cp "$REPO/setup/tc358743-1080p25.edid" "$BOOT/tc358743-1080p25.edid"

# ── Application source → /opt/dvr ────────────────────────────────────────────
echo "--- copying application source ---"
install -d "$ROOT/opt/dvr/ui"
cp -r "$REPO/src/"* "$ROOT/opt/dvr/"

# ── Systemd services ─────────────────────────────────────────────────────────
echo "--- copying systemd services ---"
install -d "$ROOT/etc/systemd/system"
cp "$REPO/systemd/tc358743.service" "$ROOT/etc/systemd/system/"
cp "$REPO/systemd/dvr.service"      "$ROOT/etc/systemd/system/"

# Symlink to enable services (equivalent to systemctl enable)
install -d "$ROOT/etc/systemd/system/multi-user.target.wants"
install -d "$ROOT/etc/systemd/system/graphical.target.wants"
ln -sf /etc/systemd/system/tc358743.service \
    "$ROOT/etc/systemd/system/multi-user.target.wants/tc358743.service" 2>/dev/null || true
ln -sf /etc/systemd/system/dvr.service \
    "$ROOT/etc/systemd/system/graphical.target.wants/dvr.service" 2>/dev/null || true

echo ""
echo "=== Deploy complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit $BOOT/wpa_supplicant.conf with your WiFi credentials"
echo "  2. Unmount SD card and insert into RPi"
echo "  3. Power on — RPi will boot and be accessible via SSH as pi@raspberrypi.local"
echo "  4. SSH in: ssh pi@raspberrypi.local  (default pass: raspberry)"
echo "  5. Run: sudo bash /boot/install.sh"
echo "  6. Run: sudo bash /boot/readonly.sh"
echo "  7. sudo reboot"
echo ""
echo "On reboot the DVR app starts automatically."
