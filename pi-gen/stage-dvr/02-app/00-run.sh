#!/bin/bash -e
# 02-app — install the DVR application to /opt/dvr.

install -d "${ROOTFS_DIR}/opt/dvr"
cp -r files/src/. "${ROOTFS_DIR}/opt/dvr/"

on_chroot <<'EOF'
chown -R pi:pi /opt/dvr
find /opt/dvr -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
EOF

echo "02-app done"
