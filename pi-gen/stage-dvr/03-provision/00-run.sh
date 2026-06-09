#!/bin/bash -e
# 03-provision — read-only-root first-boot service + Wi-Fi persistence.

install -m 755 files/dvr-provision.sh     "${ROOTFS_DIR}/usr/local/bin/dvr-provision.sh"
install -m 755 files/dvr-wifi-restore.sh  "${ROOTFS_DIR}/usr/local/bin/dvr-wifi-restore.sh"
install -m 755 files/dvr-wifi-save.sh     "${ROOTFS_DIR}/usr/local/bin/dvr-wifi-save"
install -m 755 files/dvr-config-save.sh   "${ROOTFS_DIR}/usr/local/bin/dvr-config-save"
install -m 644 files/dvr-provision.service     "${ROOTFS_DIR}/etc/systemd/system/dvr-provision.service"
install -m 644 files/dvr-wifi-restore.service  "${ROOTFS_DIR}/etc/systemd/system/dvr-wifi-restore.service"

# Let the app (user 'pi') trigger the Wi-Fi save helper as root, nothing else.
install -m 440 files/dvr-sudoers "${ROOTFS_DIR}/etc/sudoers.d/dvr"

# Writable store for saved Wi-Fi keyfiles (FAT partition, survives RO root).
install -d "${ROOTFS_DIR}/boot/firmware/dvr-wifi"

on_chroot <<'EOF'
systemctl enable dvr-provision.service
systemctl enable dvr-wifi-restore.service
EOF

echo "03-provision done"
