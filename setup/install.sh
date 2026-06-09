#!/usr/bin/env bash
# install.sh — run once as root on first writable boot
# Usage: sudo bash install.sh
set -euo pipefail

INSTALL_DIR="/opt/dvr"
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)/src"

echo "=== DVR install: updating package lists ==="
apt-get update -y

echo "=== DVR install: installing GStreamer ==="
# Lean set: base (xvimagesink, audioconvert), good (v4l2, mp4mux, level),
# bad (voaacenc), alsa, x. We use the hardware H.264 encoder (v4l2h264enc)
# and AAC via voaacenc — so NO libav, NO -ugly (x264), NO -gl, NO -dev headers.
apt-get install -y --no-install-recommends \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-alsa \
    gstreamer1.0-x \
    python3-gi \
    gir1.2-gstreamer-1.0 \
    gir1.2-gst-plugins-base-1.0

echo "=== DVR install: V4L2 tools ==="
apt-get install -y --no-install-recommends \
    v4l-utils

echo "=== DVR install: Tkinter (lean UI, no Qt needed) ==="
# python3-tk is all we need — Tkinter is in the Python stdlib.
# GStreamer xvimagesink renders into a tk.Frame XID directly (GPU path,
# same architecture as picamera.start_preview() DispmanX overlay).
apt-get install -y --no-install-recommends \
    python3-tk \
    tk8.6 \
    tcl8.6

echo "=== DVR install: audio ==="
apt-get install -y --no-install-recommends \
    alsa-utils \
    libasound2 \
    libasound2-plugins

echo "=== DVR install: networking ==="
apt-get install -y --no-install-recommends \
    network-manager \
    python3-dbus

echo "=== DVR install: USB / storage ==="
apt-get install -y --no-install-recommends \
    udisks2 \
    exfat-fuse \
    exfat-utils \
    dosfstools \
    udev

echo "=== DVR install: fonts ==="
apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    fonts-liberation

echo "=== DVR install: misc Python deps ==="
apt-get install -y --no-install-recommends \
    python3-pip \
    python3-evdev \
    python3-psutil

echo "=== DVR install: X11 minimal (for Tkinter + xvimagesink) ==="
apt-get install -y --no-install-recommends \
    xserver-xorg-core \
    xserver-xorg-input-evdev \
    xserver-xorg-input-libinput \
    xserver-xorg-video-fbdev \
    x11-xserver-utils \
    xinit \
    xterm

echo "=== DVR install: disabling unneeded services ==="
systemctl disable --now bluetooth 2>/dev/null || true
systemctl disable --now avahi-daemon 2>/dev/null || true
systemctl disable --now triggerhappy 2>/dev/null || true
systemctl disable --now cups 2>/dev/null || true
# Disable lightdm if present — we use a systemd-launched xinit instead
systemctl disable lightdm 2>/dev/null || true

echo "=== DVR install: configuring autologin on tty1 ==="
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf <<'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin pi --noclear %I $TERM
EOF

echo "=== DVR install: creating app directory ==="
mkdir -p "$INSTALL_DIR"
cp -r "$SRC_DIR"/* "$INSTALL_DIR/"
chown -R pi:pi "$INSTALL_DIR"

echo "=== DVR install: ALSA config ==="
cp "$(dirname "$0")/asound.conf" /etc/asound.conf

echo "=== DVR install: polkit rules (power + USB without root) ==="
# Lets the 'pi' user power off, reboot, and mount/eject USB via udisksctl
# without sudo or a password — needed because the app runs read-only as 'pi'.
mkdir -p /etc/polkit-1/localauthority/50-local.d
cat > /etc/polkit-1/localauthority/50-local.d/50-dvr.pkla <<'EOF'
[DVR power and storage]
Identity=unix-user:pi
Action=org.freedesktop.login1.power-off;org.freedesktop.login1.reboot;org.freedesktop.udisks2.filesystem-mount;org.freedesktop.udisks2.filesystem-mount-system;org.freedesktop.udisks2.eject-media;org.freedesktop.udisks2.power-off-drive
ResultAny=yes
ResultInactive=yes
ResultActive=yes
EOF

echo "=== DVR install: X11 config for touch ==="
mkdir -p /etc/X11/xorg.conf.d
cat > /etc/X11/xorg.conf.d/99-touch.conf <<'EOF'
Section "InputClass"
    Identifier "DSI touchscreen"
    MatchIsTouchscreen "on"
    Driver "libinput"
    Option "TransformationMatrix" "1 0 0 0 1 0 0 0 1"
EndSection
EOF

echo "=== DVR install: .xinitrc for pi user ==="
cat > /home/pi/.xinitrc <<'EOF'
#!/bin/sh
xset s off
xset -dpms
xset s noblank
unclutter -idle 1 -root &
exec python3 /opt/dvr/main.py
EOF
chown pi:pi /home/pi/.xinitrc

echo "=== DVR install: installing systemd services ==="
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)/systemd"
cp "$SCRIPT_DIR/tc358743.service" /etc/systemd/system/
cp "$SCRIPT_DIR/dvr.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable tc358743.service
systemctl enable dvr.service

echo "=== DVR install: EDID script ==="
cp "$(dirname "$0")/tc358743.sh" /usr/local/bin/tc358743-init.sh
chmod +x /usr/local/bin/tc358743-init.sh
# Copy EDID binary
cp "$(dirname "$0")/tc358743-1080p25.edid" /usr/local/share/tc358743-1080p25.edid 2>/dev/null || true

echo "=== DVR install: unclutter for hidden cursor ==="
apt-get install -y --no-install-recommends unclutter || true

echo ""
echo "=== Install complete. ==="
echo "    Next step: run 'sudo bash setup/readonly.sh' to enable read-only SD."
echo "    Then reboot."
