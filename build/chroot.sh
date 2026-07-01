#!/bin/bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "==> Updating and installing packages..."
apt-get update -y
apt-get install -y --no-install-recommends \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-alsa gstreamer1.0-x \
    python3-gi gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
    v4l-utils python3-tk python3-psutil python3-pil \
    alsa-utils network-manager udisks2 exfatprogs dosfstools parted \
    weston xwayland fonts-dejavu-core mpv overlayroot

echo "==> Configuring Boot Settings..."
FW="/boot/firmware"
cat >> "${FW}/config.txt" <<'EOF'
# ═══════════════════════ DVR appliance ═══════════════════════
dtoverlay=vc4-kms-v3d,cma-256
max_framebuffers=2
auto_initramfs=1
camera_auto_detect=0
dtoverlay=tc358743
dtoverlay=i2s-mmap
disable_splash=1
boot_delay=0
initial_turbo=30
dtoverlay=disable-bt
EOF

# Append boot-speed flags to cmdline.txt
sed -i 's/[[:space:]]*$//' "${FW}/cmdline.txt"
sed -i 's/$/ quiet loglevel=3 logo.nologo vt.global_cursor_default=0 fsck.mode=skip noswap/' "${FW}/cmdline.txt"
tr -s ' ' < "${FW}/cmdline.txt" | tr -d '\n' > "${FW}/cmdline.tmp" && mv "${FW}/cmdline.tmp" "${FW}/cmdline.txt"

echo "==> Installing DVR App..."
mkdir -p /opt/dvr/assets
cp -r /repo/src/. /opt/dvr/
cp /repo/assets/splash-800x480.png /opt/dvr/assets/splash.png
chown -R pi:pi /opt/dvr
python3 -m compileall -q /opt/dvr
mkdir -p /opt/dvr/.cache/gstreamer-1.0
GST_REGISTRY_1_0=/opt/dvr/.cache/gstreamer-1.0/registry.bin gst-inspect-1.0 >/dev/null
chown -R pi:pi /opt/dvr/.cache

echo "==> Configuring Systemd and Weston..."
cp /repo/systemd/tc358743.service /etc/systemd/system/
cp /repo/setup/tc358743.sh /usr/local/bin/tc358743-init.sh
chmod +x /usr/local/bin/tc358743-init.sh
cp /repo/setup/asound.conf /etc/asound.conf

mkdir -p /etc/polkit-1/localauthority/50-local.d
cat > /etc/polkit-1/localauthority/50-local.d/50-dvr.pkla <<'EOF'
[DVR power and storage]
Identity=unix-user:pi
Action=org.freedesktop.login1.power-off;org.freedesktop.login1.reboot;org.freedesktop.udisks2.filesystem-mount;org.freedesktop.udisks2.filesystem-mount-system;org.freedesktop.udisks2.eject-media;org.freedesktop.udisks2.power-off-drive
ResultAny=yes
ResultInactive=yes
ResultActive=yes
EOF

mkdir -p /etc/xdg/weston
cat > /etc/xdg/weston/weston.ini <<'EOF'
[core]
shell=kiosk-shell.so
xwayland=true
idle-time=0

[libinput]
enable-tap=true

[autolaunch]
path=/usr/local/bin/dvr-start.sh
EOF

cat > /usr/local/bin/dvr-start.sh <<'EOF'
#!/bin/sh
while :; do
    [ -f /boot/firmware/dvr.env ] && . /boot/firmware/dvr.env
    export DVR_WIDTH DVR_HEIGHT DVR_FPS DVR_BITRATE DVR_CLIP_SECONDS
    export GST_REGISTRY_1_0=/opt/dvr/.cache/gstreamer-1.0/registry.bin
    export GST_REGISTRY_UPDATE=no
    python3 /opt/dvr/main.py
    sleep 2
done
EOF
chmod +x /usr/local/bin/dvr-start.sh

mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf <<'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin pi --noclear %I $TERM
EOF

cat > /home/pi/.bash_profile <<'EOF'
if [ "$(tty)" = "/dev/tty1" ] && [ -z "$WAYLAND_DISPLAY" ]; then
    export XDG_RUNTIME_DIR=/run/user/$(id -u)
    if [ ! -d "$XDG_RUNTIME_DIR" ]; then
        export XDG_RUNTIME_DIR=/tmp/wayland-runtime-$(id -u)
        mkdir -p "$XDG_RUNTIME_DIR"
        chmod 700 "$XDG_RUNTIME_DIR"
    fi
    exec weston --shell=kiosk-shell.so >/dev/null 2>&1
fi
EOF
chown pi:pi /home/pi/.bash_profile

cat > "${FW}/dvr.env" <<'EOF'
# DVR config — edit on the SD card, takes effect on next boot.
# Capture resolution MUST match what your HDMI source sends.
#DVR_WIDTH=1280
#DVR_HEIGHT=720
#DVR_FPS=25/1
#DVR_BITRATE=10000000
#DVR_CLIP_SECONDS=1800
EOF

echo "==> Masking services for lightning fast boot..."
systemctl set-default multi-user.target
systemctl enable tc358743.service

for unit in \
    bluetooth.service hciuart.service ModemManager.service \
    triggerhappy.service triggerhappy.socket avahi-daemon.service avahi-daemon.socket \
    dphys-swapfile.service rpi-eeprom-update.service \
    man-db.timer apt-daily.timer apt-daily-upgrade.timer \
    e2scrub_all.timer e2scrub_reap.service systemd-rfkill.service systemd-rfkill.socket \
    keyboard-setup.service \
    NetworkManager-wait-online.service systemd-networkd-wait-online.service rng-tools-debian ; do
    systemctl disable "$unit" 2>/dev/null || true
    systemctl mask    "$unit" 2>/dev/null || true
done

echo "==> Provisioning Read-only and Wi-Fi persistence scripts..."
cp /repo/setup/dvr-provision.sh /usr/local/bin/
cp /repo/setup/dvr-wifi-restore.sh /usr/local/bin/
cp /repo/setup/dvr-wifi-save.sh /usr/local/bin/dvr-wifi-save
cp /repo/setup/dvr-config-save.sh /usr/local/bin/dvr-config-save
chmod +x /usr/local/bin/dvr-provision.sh /usr/local/bin/dvr-wifi-restore.sh /usr/local/bin/dvr-wifi-save /usr/local/bin/dvr-config-save

cp /repo/systemd/dvr-provision.service /etc/systemd/system/
cp /repo/systemd/dvr-wifi-restore.service /etc/systemd/system/
systemctl enable dvr-provision.service dvr-wifi-restore.service

cp /repo/setup/dvr-sudoers /etc/sudoers.d/dvr
chmod 440 /etc/sudoers.d/dvr
mkdir -p /boot/firmware/dvr-wifi

echo "==> Cleaning up apt cache..."
if ! mountpoint -q /var/cache/apt/archives; then
    apt-get clean
fi
rm -rf /var/lib/apt/lists/*
