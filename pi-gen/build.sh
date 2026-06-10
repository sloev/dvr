#!/usr/bin/env bash
# build.sh — reproducibly build the DVR appliance image with pi-gen.
#
# Requirements on the build host (Debian/Ubuntu or any Docker host):
#   - docker
#   - qemu-user-static + binfmt-support  (for armhf emulation on x86;
#     pi-gen's docker image registers binfmt automatically on most hosts)
#
# Usage:
#   ./build.sh              # clone pi-gen (pinned), stage sources, build
#   PIGEN_REF=2024-07-04-raspios-bookworm ./build.sh   # pin a dated tag
#
# Output: pi-gen/pi-gen-src/deploy/*.img.xz
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
PIGEN_DIR="${PIGEN_DIR:-$HERE/pi-gen-src}"
PIGEN_REF="${PIGEN_REF:-bookworm}"     # 'bookworm' branch = 32-bit armhf
STAGE="$HERE/stage-dvr"

echo "==> pi-gen at $PIGEN_DIR (ref: $PIGEN_REF)"
if [ ! -d "$PIGEN_DIR/.git" ]; then
    git clone --depth 1 --branch "$PIGEN_REF" \
        https://github.com/RPi-Distro/pi-gen "$PIGEN_DIR"
fi

echo "==> Staging DVR sources into the custom stage (single source of truth)"
rm -rf "$STAGE/01-system/files/setup" \
       "$STAGE/01-system/files/systemd" \
       "$STAGE/02-app/files/src" \
       "$STAGE/02-app/files/assets"
mkdir -p "$STAGE/01-system/files" "$STAGE/02-app/files/assets"
cp -r "$REPO/setup"   "$STAGE/01-system/files/setup"
cp -r "$REPO/systemd" "$STAGE/01-system/files/systemd"
cp -r "$REPO/src"     "$STAGE/02-app/files/src"
# Screen-sized boot splash, deployed next to the app at /opt/dvr/assets.
cp "$REPO/assets/splash-800x480.png" "$STAGE/02-app/files/assets/splash.png"

echo "==> Copying stage + config into pi-gen"
# Must be a real directory, not a symlink: pi-gen's Dockerfile does
# `COPY . /pi-gen/`, baking the tree into the build image. An absolute
# symlink to the host path dangles inside the container and makes
# `realpath stage-dvr` fail ("No such file or directory").
rm -rf "$PIGEN_DIR/stage-dvr"
cp -r "$STAGE" "$PIGEN_DIR/stage-dvr"
cp "$HERE/config" "$PIGEN_DIR/config"
# Don't export the intermediate Lite image — we only want the final one.
touch "$PIGEN_DIR/stage2/SKIP_IMAGES"

echo "==> Building (Docker)"
cd "$PIGEN_DIR"
./build-docker.sh

echo ""
echo "==> Done. Image(s):"
ls -lh "$PIGEN_DIR/deploy/" 2>/dev/null || true
echo "Flash with Raspberry Pi Imager (set Wi-Fi/country in the gear menu) or:"
echo "  xzcat deploy/*.img.xz | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync"
