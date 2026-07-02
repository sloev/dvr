#!/bin/sh
set -e

echo "Starting Alpine OS Build for Raspberry Pi (aarch64)..."

# Configuration
ARCH="aarch64"
ALPINE_BRANCH="edge"
MIRROR="http://dl-cdn.alpinelinux.org/alpine"
ROOTFS_DIR="rootfs"
IMG_FILE="dvr_alpine_aarch64.img"

# Required packages
PACKAGES="alpine-base linux-rpi raspberrypi-bootloader v4l-utils libdrm mesa-egl mesa-gles mesa-gbm mesa-dri-gallium gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad libinput eudev rust cargo pkgconf fontconfig-dev openrc"

echo "Installing host dependencies for compilation..."
apk add --no-cache rust cargo gcc g++ pkgconf gstreamer-dev gst-plugins-base-dev fontconfig-dev

echo "Building dvr_app..."
cd dvr_app
cargo build --release
cd ..

echo "Downloading alpine-make-rootfs..."
wget -qO alpine-make-rootfs https://raw.githubusercontent.com/alpinelinux/alpine-make-rootfs/v0.7.0/alpine-make-rootfs
chmod +x alpine-make-rootfs

echo "Building rootfs..."
mkdir -p "$ROOTFS_DIR"

./alpine-make-rootfs \
    --packages "$PACKAGES" \
    --branch "$ALPINE_BRANCH" \
    --arch "$ARCH" \
    --script-chroot \
    "$ROOTFS_DIR" \
    <<-'EOF'
#!/bin/sh
set -e

# Enable necessary services
rc-update add udev sysinit
rc-update add udev-trigger sysinit
rc-update add udev-settle sysinit
rc-update add sysfs sysinit
rc-update add devfs sysinit
rc-update add modules boot

# Configure boot
mkdir -p /boot
echo "dtoverlay=vc4-kms-v3d" >> /boot/config.txt
echo "dtoverlay=tc358743" >> /boot/config.txt
echo "console=tty1 root=/dev/mmcblk0p2 rootfstype=ext4 rw rootwait" > /boot/cmdline.txt

# Create CSI-2 bridge initialization init script
cat > /etc/init.d/csi2-bridge << 'INIT'
#!/sbin/openrc-run
description="Initialize CSI-2 bridge"

depend() {
    need devfs sysfs modules
}

start() {
    ebegin "Starting CSI-2 bridge initialization"
    eend 0
}
INIT
chmod +x /etc/init.d/csi2-bridge
rc-update add csi2-bridge boot

# Enable autologin for root (for testing/DVR app run)
sed -i 's/^tty1::respawn:\/sbin\/getty 38400 tty1/tty1::respawn:\/usr\/local\/bin\/dvr_app/' /etc/inittab

EOF

echo "Copying compiled dvr_app into rootfs..."
mkdir -p "$ROOTFS_DIR/usr/local/bin"
cp dvr_app/target/release/dvr_app "$ROOTFS_DIR/usr/local/bin/"

echo "Rootfs built successfully."

echo "Creating image file..."
# Create a 2GB raw image
dd if=/dev/zero of="$IMG_FILE" bs=1M count=2048

# Partition the image (500MB boot FAT32, rest root ext4)
parted -s "$IMG_FILE" mklabel msdos
parted -s "$IMG_FILE" mkpart primary fat32 1MiB 500MiB
parted -s "$IMG_FILE" set 1 boot on
parted -s "$IMG_FILE" mkpart primary ext4 500MiB 100%

# Loop mount the image
LOOP_DEV=$(losetup -fP --show "$IMG_FILE")

# Format partitions
mkfs.vfat -F 32 "${LOOP_DEV}p1"
mkfs.ext4 -F "${LOOP_DEV}p2"

# Mount partitions
mkdir -p mnt_img
mount "${LOOP_DEV}p2" mnt_img
mkdir -p mnt_img/boot
mount "${LOOP_DEV}p1" mnt_img/boot

# Copy rootfs to image
echo "Copying rootfs to image..."
cp -a "$ROOTFS_DIR"/* mnt_img/

# Cleanup
umount mnt_img/boot
umount mnt_img
rm -rf mnt_img
losetup -d "$LOOP_DEV"

echo "Build complete: $IMG_FILE"
