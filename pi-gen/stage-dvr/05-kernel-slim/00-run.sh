#!/bin/bash -e
# 05-kernel-slim — keep only the ARMv7 (v7) kernel; drop the other flavors.
#
# pi-gen (stage0/02-firmware/01-packages) installs FOUR Raspberry Pi kernels so
# a single card boots any model:
#     v6  -> kernel.img    Pi 1 / Zero            (ARMv6)
#     v7  -> kernel7.img   Pi 2 / Pi 3 (32-bit)   (ARMv7)   <-- the only one we use
#     v7l -> kernel7l.img  Pi 4 / 400 (32-bit)    (ARMv7 LPAE)
#     v8  -> kernel8.img   64-bit (Pi 3/4/Zero2)
#
# This appliance targets the Pi 2B and 3B in 32-bit mode, which both boot the
# v7 kernel. The other three kernels, their module trees, every linux-headers-*
# (no DKMS/out-of-tree builds here — the TC358743 driver is in-kernel), and
# three of the four update-initramfs runs in export-image are pure waste, in
# both image size and (emulated) build time.
#
# They are independent top-level packages, so purging them does NOT cascade
# into the v7 kernel.
#
# ⚠ BOOT-CRITICAL: this removes kernels. If a target board ever fails to boot,
# revert this substage first (delete the 05-kernel-slim dir). Verified for the
# Pi 2B / 3B (32-bit) targets only — add the relevant flavor back before using
# any other model.

on_chroot <<'CHROOT'
set -e
export DEBIAN_FRONTEND=noninteractive

DROP="
linux-image-rpi-v6 linux-image-rpi-v7l linux-image-rpi-v8
linux-headers-rpi-v6 linux-headers-rpi-v7 linux-headers-rpi-v7l linux-headers-rpi-v8
"
to_drop=""
for p in $DROP; do
    dpkg -s "$p" >/dev/null 2>&1 && to_drop="$to_drop $p"
done
if [ -n "$to_drop" ]; then
    echo "kernel-slim: purging$to_drop"
    apt-get purge -y $to_drop
fi
apt-get autoremove --purge -y
apt-get clean

# The v7 kernel MUST survive — fail the build loudly rather than ship an
# unbootable image.
dpkg -s linux-image-rpi-v7 >/dev/null 2>&1 || {
    echo "FATAL kernel-slim: linux-image-rpi-v7 was removed!" >&2
    exit 1
}
CHROOT

echo "05-kernel-slim done"
