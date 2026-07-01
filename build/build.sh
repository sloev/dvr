#!/bin/bash
set -eo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (or use sudo)"
  exit 1
fi

echo "==> Setting up dependencies..."
apt-get update -y
apt-get install -y qemu-user-static systemd-container parted e2fsprogs wget xz-utils curl

IMG_XZ="base.img.xz"
WORK_IMG="dvr-build.img"

if [ ! -f "$IMG_XZ" ]; then
    echo "Error: $IMG_XZ not found. Please download it first."
    exit 1
fi

echo "==> Decompressing image..."
rm -f "$WORK_IMG"
unxz -k -c "$IMG_XZ" > "$WORK_IMG"

echo "==> Expanding image to fit new packages (adding 800MB)..."
dd if=/dev/zero bs=1M count=800 >> "$WORK_IMG"
parted "$WORK_IMG" resizepart 2 100%

LOOP_DEV=$(losetup -fP --show "$WORK_IMG")
echo "==> Resizing filesystem on ${LOOP_DEV}p2..."
e2fsck -p -f "${LOOP_DEV}p2"
resize2fs "${LOOP_DEV}p2"

echo "==> Mounting image..."
mkdir -p mnt
mount "${LOOP_DEV}p2" mnt
mount "${LOOP_DEV}p1" mnt/boot/firmware

# Copy qemu-arm-static so chroot works natively on x86 CI runners
cp /usr/bin/qemu-arm-static mnt/usr/bin/

echo "==> Running chroot provisioning via systemd-nspawn..."
# We bind-mount the entire repo into /repo so the chroot script can copy src/ and systemd/
mkdir -p apt-cache-armhf
mkdir -p mnt/var/cache/apt/archives
systemd-nspawn --quiet -D mnt --bind-ro="$(pwd)":/repo --bind="$(pwd)/apt-cache-armhf":/var/cache/apt/archives /bin/bash /repo/build/chroot.sh

echo "==> Unmounting..."
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
