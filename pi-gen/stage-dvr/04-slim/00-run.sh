#!/bin/bash -e
# 04-slim — strip appliance-irrelevant packages and data to shrink the image.
#
# The base "Lite" stage (stage2) installs a developer/desktop-ish userland with
# recommends: a full build toolchain, the GPIO/I2C/SPI Python stack, libcamera
# (rpicam-apps), archive tools, foreign-filesystem helpers, and daemons we
# explicitly disable. None of it is used by the DVR appliance.
#
# Confirmed runtime deps of the app are only: mpv, v4l2-ctl (v4l-utils),
# udisksctl (udisks2), mkfs.exfat (exfatprogs), nmcli (network-manager),
# systemctl, xset (x11-xserver-utils). CPU temp is read from
# /sys/class/thermal, so vcgencmd / raspi-utils are NOT needed either.
#
# Runs last in stage-dvr (after the app + provisioning are installed) and
# before EXPORT_IMAGE, so the smaller rootfs is what gets sized and exported.

on_chroot <<'CHROOT'
set -e
export DEBIAN_FRONTEND=noninteractive

# Leaf packages safe to remove on a capture appliance. Anything not actually
# installed is skipped; orphaned dependencies are swept by autoremove below.
PURGE="
build-essential gdb manpages-dev pkg-config strace ltrace ed
git git-man make
python3-pip python3-setuptools python3-wheel
pigpio python3-pigpio gpiod python3-libgpiod python3-gpiozero
raspi-gpio python3-rpi-lgpio python3-spidev python3-smbus2
lua5.1 luajit
mkvtoolnix rpicam-apps-lite
p7zip-full zip unzip
nfs-common cifs-utils usb-modeswitch libmtp-runtime
rpi-update apt-listchanges
pi-bluetooth
avahi-daemon
dphys-swapfile
htop ncdu ssh-import-id
"

to_purge=""
for p in $PURGE; do
    if dpkg -s "$p" >/dev/null 2>&1; then
        to_purge="$to_purge $p"
    fi
done
if [ -n "$to_purge" ]; then
    echo "slim: purging$to_purge"
    apt-get purge -y $to_purge
fi
apt-get autoremove --purge -y
apt-get clean

# Safety net: a purge that cascaded into anything load-bearing must fail the
# build loudly rather than ship a broken image.
for keep in \
    network-manager wpasupplicant udisks2 \
    mpv v4l-utils exfatprogs dosfstools \
    xserver-xorg-core xserver-xorg-legacy xinit x11-xserver-utils \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-x gstreamer1.0-alsa \
    python3 python3-gi python3-tk python3-psutil \
    fonts-dejavu-core \
    systemd udev overlayroot ; do
    if ! dpkg -s "$keep" >/dev/null 2>&1; then
        echo "FATAL slim: required package '$keep' was removed!" >&2
        exit 1
    fi
done

# Drop docs, man and info pages (pi-gen only hardlinks docs at export; nothing
# strips man/info). Guarded by the export step's own -f checks.
rm -rf /usr/share/man/* /usr/share/info/* \
       /usr/share/doc/* /usr/share/lintian \
       /var/cache/apt/archives/*.deb 2>/dev/null || true

# Keep only the en_US locale data.
find /usr/share/locale -mindepth 1 -maxdepth 1 -type d \
     ! -name 'en_US*' ! -name 'en' ! -name 'C*' \
     -exec rm -rf {} + 2>/dev/null || true
CHROOT

echo "04-slim done"
