#!/bin/bash
set -eo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (or use sudo)"
  exit 1
fi

WORK_IMG="dvr-build.img"

if [ ! -f "$WORK_IMG" ]; then
    echo "Error: $WORK_IMG not found. Phase 1 failed."
    exit 1
fi

LOOP_DEV=$(losetup -fP --show "$WORK_IMG")

echo "==> Mounting image..."
mkdir -p mnt
mount "${LOOP_DEV}p2" mnt
mount "${LOOP_DEV}p1" mnt/boot/firmware

echo "==> Running App provisioning via systemd-nspawn..."
systemd-nspawn --quiet -D mnt --bind-ro="$(pwd)":/repo /bin/bash /repo/build/chroot-app.sh

echo "==> Unmounting Phase 2..."
sync
umount mnt/boot/firmware
umount mnt
losetup -d "$LOOP_DEV"

echo "==> Shrinking final image..."
if [ ! -f "pishrink.sh" ]; then
    wget -qO pishrink.sh https://raw.githubusercontent.com/Drewsif/PiShrink/master/pishrink.sh
    chmod +x pishrink.sh
fi
./pishrink.sh -s -a "$WORK_IMG" "dvr-latest-armhf.img"

echo "==> Compressing output..."
xz -T0 -3 -f "dvr-latest-armhf.img"

echo "==> Done: dvr-latest-armhf.img.xz"
