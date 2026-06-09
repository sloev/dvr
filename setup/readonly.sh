#!/usr/bin/env bash
# readonly.sh — configure overlayfs read-only root
# Run ONCE as root after install.sh, then reboot.
# The SD card root becomes read-only; all writes go to a tmpfs overlay.
# USB storage remains writable.
set -euo pipefail

echo "=== Enabling read-only root via overlayroot ==="

# Install overlayroot (part of cloud-initramfs-tools on Debian/Ubuntu)
apt-get install -y --no-install-recommends overlayroot

# Configure overlayroot to use tmpfs as the upper layer
cat > /etc/overlayroot.conf <<'EOF'
# Use tmpfs for the writable overlay — changes are lost on reboot.
# This keeps the SD card read-only and extends its life significantly.
overlayroot="tmpfs:swap=0,recurse=0"
overlayroot_cfgdisk="disabled"
EOF

# Ensure /tmp and /var/log are tmpfs so logs don't fill the overlay
if ! grep -q "tmpfs /tmp" /etc/fstab; then
    echo "tmpfs   /tmp        tmpfs   defaults,noatime,nosuid,size=64m    0 0" >> /etc/fstab
fi
if ! grep -q "tmpfs /var/log" /etc/fstab; then
    echo "tmpfs   /var/log    tmpfs   defaults,noatime,nosuid,size=32m    0 0" >> /etc/fstab
fi
if ! grep -q "tmpfs /var/tmp" /etc/fstab; then
    echo "tmpfs   /var/tmp    tmpfs   defaults,noatime,nosuid,size=16m    0 0" >> /etc/fstab
fi

# NetworkManager state needs to survive reboots so learned WiFi networks persist.
# We keep NM state on the USB drive via a bind mount set up at runtime by the app.
# As a fallback, persist wpa_supplicant configs on the boot partition (rw).
mkdir -p /boot/wifi
if ! grep -q "/boot/wifi" /etc/fstab; then
    echo "/boot/wifi  /etc/NetworkManager/system-connections  none  bind  0 0" >> /etc/fstab
fi

# Move existing NM connections to /boot/wifi so they survive
cp -r /etc/NetworkManager/system-connections/. /boot/wifi/ 2>/dev/null || true

# Update initramfs to include overlayroot
update-initramfs -u

echo ""
echo "=== Read-only setup complete. ==="
echo "    Reboot now: sudo reboot"
echo "    After reboot the SD root is read-only."
echo "    To make temporary changes: sudo overlayroot-chroot"
