#!/bin/bash -e
# 02-app — install the DVR application to /opt/dvr.

install -d "${ROOTFS_DIR}/opt/dvr"
cp -r files/src/. "${ROOTFS_DIR}/opt/dvr/"

# Boot/startup splash, loaded by the app at /opt/dvr/assets/splash.png.
install -d "${ROOTFS_DIR}/opt/dvr/assets"
cp -r files/assets/. "${ROOTFS_DIR}/opt/dvr/assets/"

on_chroot <<'EOF'
chown -R pi:pi /opt/dvr
find /opt/dvr -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

# Precompile python to avoid pycache generation on every boot
python3 -m compileall -q /opt/dvr

# Bake GStreamer registry cache so it doesn't scan plugins on boot
mkdir -p /opt/dvr/.cache/gstreamer-1.0
GST_REGISTRY_1_0=/opt/dvr/.cache/gstreamer-1.0/registry.bin gst-inspect-1.0 >/dev/null
chown -R pi:pi /opt/dvr/.cache
EOF

echo "02-app done"
