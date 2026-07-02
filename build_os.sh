#!/bin/sh
set -e

VERSION=${VERSION:-"latest"}
echo "Starting Alpine OS Build for Raspberry Pi (aarch64) - DVR Edition..."
echo "Version: $VERSION"

# Configuration
ARCH="aarch64"
ALPINE_BRANCH="edge"
MIRROR="http://dl-cdn.alpinelinux.org/alpine"
ROOTFS_DIR="rootfs"
IMG_FILE="dvr_alpine_aarch64_${VERSION}.img"

# Required packages
PACKAGES="alpine-base linux-rpi raspberrypi-bootloader v4l-utils libdrm mesa-egl mesa-gles mesa-gbm mesa-dri-gallium gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad libinput eudev pkgconf fontconfig-dev openrc hostapd dnsmasq util-linux e2fsprogs f2fs-tools wpa_supplicant"

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
    <<EOF
#!/bin/sh
set -e

# Enable necessary services
rc-update add udev sysinit
rc-update add udev-trigger sysinit
rc-update add udev-settle sysinit
rc-update add sysfs sysinit
rc-update add devfs sysinit
rc-update add modules boot
rc-update add hostapd default
rc-update add dnsmasq default
rc-update add local default

# Configure boot
mkdir -p /boot
echo "dtoverlay=vc4-kms-v3d" >> /boot/config.txt
echo "dtoverlay=tc358743" >> /boot/config.txt
echo "gpu_mem=256" >> /boot/config.txt
echo "quiet loglevel=1 vt.global_cursor_default=0 root=/dev/mmcblk0p2 rootfstype=ext4 ro rootwait" > /boot/cmdline.txt

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

# Create splash image
cat > /etc/init.d/fbsplash << 'SPLASH'
#!/sbin/openrc-run
description="Show Boot Splash"

depend() {
    need devfs sysfs
    before csi2-bridge
}

start() {
    ebegin "Starting fbsplash"
    # Fallback to blanking the framebuffer if fbsplash isn't fully configured
    dd if=/dev/zero of=/dev/fb0 bs=1M count=8 2>/dev/null || true
    eend 0
}
SPLASH
chmod +x /etc/init.d/fbsplash
rc-update add fbsplash boot

# Replace getty with DVR app
sed -i 's/^tty1::respawn:\/sbin\/getty 38400 tty1/tty1::respawn:\/usr\/local\/bin\/dvr_app/' /etc/inittab

# Setup Read-Only rootfs fstab
cat > /etc/fstab << 'FSTAB'
/dev/mmcblk0p1  /boot           vfat    defaults,ro             0 0
/dev/mmcblk0p2  /               ext4    defaults,ro             0 0
/dev/mmcblk0p3  /mnt/dvr_storage f2fs   defaults,noatime,rw     0 0
tmpfs           /var/log        tmpfs   defaults,noatime,mode=0755 0 0
tmpfs           /tmp            tmpfs   defaults,noatime,mode=1777 0 0
tmpfs           /run            tmpfs   defaults,noatime,mode=0755 0 0
FSTAB

# Setup AP Networking
mkdir -p /etc/hostapd
cat > /etc/hostapd/hostapd.conf << 'HOSTAPD'
interface=wlan0
driver=nl80211
ssid=DVR_DASHCAM_AP
hw_mode=g
channel=7
wpa=2
wpa_passphrase=dashcam_wifi
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
HOSTAPD

cat > /etc/dnsmasq.conf << 'DNSMASQ'
interface=wlan0
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
DNSMASQ

cat > /etc/network/interfaces << 'IFACES'
auto lo
iface lo inet loopback

auto wlan0
iface wlan0 inet static
    address 192.168.4.1
    netmask 255.255.255.0
IFACES
EOF

echo "Injecting pre-compiled dvr_app into rootfs..."
if [ -f "dvr_app/target/release/dvr_app" ]; then
    mkdir -p "$ROOTFS_DIR/usr/local/bin"
    cp dvr_app/target/release/dvr_app "$ROOTFS_DIR/usr/local/bin/"
else
    echo "ERROR: dvr_app binary not found at dvr_app/target/release/dvr_app! Did you compile it first?"
    exit 1
fi

mkdir -p "$ROOTFS_DIR/mnt/dvr_storage"

echo "Rootfs built successfully."

echo "Creating image file..."
# Create a 4GB raw image
dd if=/dev/zero of="$IMG_FILE" bs=1M count=4096

# Partition the image (500MB boot FAT32, 1.5GB root ext4, rest storage F2FS)
parted -s "$IMG_FILE" mklabel msdos
parted -s "$IMG_FILE" mkpart primary fat32 1MiB 500MiB
parted -s "$IMG_FILE" set 1 boot on
parted -s "$IMG_FILE" mkpart primary ext4 500MiB 2000MiB
parted -s "$IMG_FILE" mkpart primary ext4 2000MiB 100%

# Loop mount the image
LOOP_DEV=$(losetup -fP --show "$IMG_FILE")

# Format partitions
mkfs.vfat -F 32 "${LOOP_DEV}p1"
mkfs.ext4 -F "${LOOP_DEV}p2"
mkfs.f2fs -f "${LOOP_DEV}p3"

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
