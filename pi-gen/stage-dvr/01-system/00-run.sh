#!/bin/bash -e
# 01-system — boot config, capture device init, kiosk autostart, boot-speed.
# Runs on the host with ${ROOTFS_DIR} pointing at the image rootfs and the
# on_chroot helper available. CWD is this substage dir (so files/ is relative).

FW="${ROOTFS_DIR}/boot/firmware"        # Bookworm: FAT partition lives here

# ── 1. config.txt — append the DVR hardware block ────────────────────────────
cat >> "${FW}/config.txt" <<'EOF'

# ═══════════════════════ DVR appliance ═══════════════════════
# KMS + CMA for the hardware H.264 encoder (v4l2h264enc) and ISP (v4l2convert).
dtoverlay=vc4-kms-v3d,cma-256
max_framebuffers=2

# Load an initramfs — required by overlayroot for the read-only root.
auto_initramfs=1

# TC358743 HDMI→CSI-2 capture (C790). Disable auto camera detect that clashes.
camera_auto_detect=0
dtoverlay=tc358743
# 4-lane CSI (CM4/Pi5): dtoverlay=tc358743,4lane=1

# I2S audio from the capture board (HDMI audio on GPIO 18-21).
dtoverlay=i2s-mmap

# ── Boot speed ──
disable_splash=1
boot_delay=0
# Brief CPU turbo through boot, then settle.
initial_turbo=30
# Skip Bluetooth init (frees a UART and shaves boot time; we don't use BT).
dtoverlay=disable-bt
EOF

# ── 2. cmdline.txt — fast, quiet, read-only-friendly boot ────────────────────
# Preserve the existing root=PARTUUID token; just append boot-speed flags and
# strip the noisy console. fsck is skipped because root becomes read-only.
CMDLINE="${FW}/cmdline.txt"
# Remove trailing newline, append our flags on the single cmdline line.
sed -i 's/[[:space:]]*$//' "$CMDLINE"
sed -i 's/$/ quiet loglevel=3 logo.nologo vt.global_cursor_default=0 fsck.mode=skip noswap/' "$CMDLINE"
# Collapse to one line (cmdline.txt must be a single line).
tr -s ' ' < "$CMDLINE" | tr -d '\n' > "${CMDLINE}.tmp" && mv "${CMDLINE}.tmp" "$CMDLINE"

# ── 3. ALSA (I2S capture) ────────────────────────────────────────────────────
install -m 644 files/setup/asound.conf "${ROOTFS_DIR}/etc/asound.conf"

# ── 4. polkit — power + USB for user 'pi' without root ───────────────────────
install -d "${ROOTFS_DIR}/etc/polkit-1/localauthority/50-local.d"
cat > "${ROOTFS_DIR}/etc/polkit-1/localauthority/50-local.d/50-dvr.pkla" <<'EOF'
[DVR power and storage]
Identity=unix-user:pi
Action=org.freedesktop.login1.power-off;org.freedesktop.login1.reboot;org.freedesktop.udisks2.filesystem-mount;org.freedesktop.udisks2.filesystem-mount-system;org.freedesktop.udisks2.eject-media;org.freedesktop.udisks2.power-off-drive
ResultAny=yes
ResultInactive=yes
ResultActive=yes
EOF

# ── 5. TC358743 init script + EDID, and its oneshot service ──────────────────
install -m 755 files/setup/tc358743.sh "${ROOTFS_DIR}/usr/local/bin/tc358743-init.sh"
if [ -f files/setup/tc358743-1080p25.edid ]; then
    install -m 644 files/setup/tc358743-1080p25.edid \
        "${ROOTFS_DIR}/usr/local/share/tc358743-1080p25.edid"
fi
install -m 644 files/systemd/tc358743.service \
    "${ROOTFS_DIR}/etc/systemd/system/tc358743.service"

# ── 6. Kiosk autostart: autologin tty1 → weston → app (Wayland/Weston) ───
install -d "${ROOTFS_DIR}/etc/xdg/weston"
cat > "${ROOTFS_DIR}/etc/xdg/weston/weston.ini" <<'EOF'
[core]
shell=kiosk-shell.so
xwayland=true
idle-time=0

[libinput]
enable-tap=true

[shell]
client=/usr/local/bin/dvr-start.sh
EOF

# Start wrapper script that loads dvr.env and restarts the app if it exits
cat > "${ROOTFS_DIR}/usr/local/bin/dvr-start.sh" <<'EOF'
#!/bin/sh
while :; do
    [ -f /boot/firmware/dvr.env ] && . /boot/firmware/dvr.env
    export DVR_WIDTH DVR_HEIGHT DVR_FPS DVR_BITRATE DVR_CLIP_SECONDS
    python3 /opt/dvr/main.py
    sleep 2
done
EOF
chmod +x "${ROOTFS_DIR}/usr/local/bin/dvr-start.sh"

# Autologin on tty1
install -d "${ROOTFS_DIR}/etc/systemd/system/getty@tty1.service.d"
cat > "${ROOTFS_DIR}/etc/systemd/system/getty@tty1.service.d/autologin.conf" <<'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin pi --noclear %I $TERM
EOF

# Launch Weston only on tty1, once.
cat > "${ROOTFS_DIR}/home/pi/.bash_profile" <<'EOF'
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

# Seed a documented, commented env file on the FAT partition.
cat > "${FW}/dvr.env" <<'EOF'
# DVR config — edit on the SD card, takes effect on next boot.
# Capture resolution MUST match what your HDMI source sends.
#   2B / 720p test:  uncomment the next two lines
#DVR_WIDTH=1280
#DVR_HEIGHT=720
#DVR_FPS=25/1
#DVR_BITRATE=10000000
#DVR_CLIP_SECONDS=1800
EOF
on_chroot <<'EOF'
chown pi:pi /home/pi/.bash_profile
EOF

# ── 7. Enable our services; disable graphical target (we use startx) ─────────
on_chroot <<'EOF'
systemctl enable tc358743.service
systemctl set-default multi-user.target
EOF

# ── 8. Boot speed: mask everything we don't need on an offline appliance ─────
on_chroot <<'EOF'
# The big one: never block boot waiting for the network.
systemctl disable NetworkManager-wait-online.service 2>/dev/null || true
systemctl mask    NetworkManager-wait-online.service 2>/dev/null || true
systemctl mask systemd-networkd-wait-online.service 2>/dev/null || true

for unit in \
    bluetooth.service hciuart.service \
    ModemManager.service \
    triggerhappy.service triggerhappy.socket \
    avahi-daemon.service avahi-daemon.socket \
    dphys-swapfile.service \
    rpi-eeprom-update.service \
    man-db.timer apt-daily.timer apt-daily-upgrade.timer \
    e2scrub_all.timer e2scrub_reap.service \
    systemd-rfkill.service systemd-rfkill.socket \
    keyboard-setup.service ; do
    systemctl disable "$unit" 2>/dev/null || true
    systemctl mask    "$unit" 2>/dev/null || true
done

# Keep time sync but don't let it gate boot.
systemctl disable rng-tools-debian 2>/dev/null || true
EOF

echo "01-system done"
