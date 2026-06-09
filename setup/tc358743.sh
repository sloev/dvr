#!/usr/bin/env bash
# tc358743-init.sh — inject EDID and configure TC358743 capture device
# Run by tc358743.service before the DVR app starts.
set -euo pipefail

EDID_FILE="/usr/local/share/tc358743-1080p25.edid"
DEVICE=""

# Find the TC358743 video device
for dev in /dev/video*; do
    if v4l2-ctl --device="$dev" --info 2>/dev/null | grep -qi "tc358743"; then
        DEVICE="$dev"
        break
    fi
done

if [ -z "$DEVICE" ]; then
    echo "tc358743: device not found, trying /dev/video0"
    DEVICE="/dev/video0"
fi

echo "tc358743: using device $DEVICE"

# Load EDID — tells the HDMI source what modes we accept
if [ -f "$EDID_FILE" ]; then
    v4l2-ctl --device="$DEVICE" --set-edid=file="$EDID_FILE" --fix-edid-checksums
    echo "tc358743: EDID loaded from $EDID_FILE"
else
    echo "tc358743: EDID file not found, loading minimal 1080p25 EDID inline"
    # Minimal EDID for 1080p25 — generated from edid-decode / modeline tool
    # This 128-byte base EDID advertises 1920x1080@25Hz as preferred mode
    python3 - <<'PYEOF'
import subprocess, struct, os

# Minimal 128-byte EDID advertising 1920x1080@25Hz preferred
edid = bytearray(128)
# Header
edid[0:8] = [0x00,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0x00]
# Manufacturer: "RPI" (made-up), product 0x0001, serial 0, week 1, year 2020
edid[8:18]  = [0x52,0x50,0x00,0x01,0x00,0x00,0x00,0x00,0x01,0x1E]
# Version 1.3
edid[18:20] = [0x01,0x03]
# Video input: digital, 8-bit, HDMI-a
edid[20]    = 0xA0
# Screen size 16cm x 9cm (aspect)
edid[21:23] = [0x10,0x09]
# Gamma 2.2
edid[23]    = 0x78
# Feature support: RGB, preferred timing in DTD
edid[24]    = 0x0A
# Chromaticity (sRGB default zeros)
edid[25:35] = [0x00]*10
# Established timings: none
edid[35:38] = [0x00,0x00,0x00]
# Standard timings: unused
edid[38:54] = [0x01,0x01]*8
# Descriptor 1: Detailed Timing for 1920x1080 @ 25 Hz
# Pixel clock: 74250 kHz → 7425 in units of 10kHz = 0x1E01 (little-endian)
# Htotal=2640 Hactive=1920 Hblank=720
# Vtotal=1125 Vactive=1080 Vblank=45
# Use standard CEA 1080p25 timings
pclk = 7425  # 74.25 MHz in units of 10 kHz
edid[54:56] = struct.pack('<H', pclk)
# Hactive LSB=0x80 (1920 & 0xFF), Hblank LSB=0xD0 (720 & 0xFF)
edid[56] = 1920 & 0xFF
edid[57] = 720  & 0xFF
edid[58] = ((1920 >> 4) & 0xF0) | ((720 >> 8) & 0x0F)
# Vactive LSB=0x38 (1080 & 0xFF), Vblank LSB=0x2D (45 & 0xFF)
edid[59] = 1080 & 0xFF
edid[60] = 45   & 0xFF
edid[61] = ((1080 >> 4) & 0xF0) | ((45 >> 8) & 0x0F)
# Sync offsets/widths (1080p25 CEA): Hsync offset=528, width=44; Vsync offset=4, width=5
edid[62] = 528 & 0xFF
edid[63] = 44  & 0xFF
edid[64] = ((4 & 0x0F) << 4) | (5 & 0x0F)
edid[65] = ((528 >> 8) & 0x03) << 6 | ((44 >> 8) & 0x03) << 4 | ((4 >> 4) & 0x03) << 2 | ((5 >> 4) & 0x03)
# Image size: 1600x900 mm (arbitrary, not used by tc358743)
edid[66] = 0x40
edid[67] = 0x84
edid[68] = 0x00
# Border: 0
edid[69:71] = [0x00,0x00]
# Flags: interlaced=0, stereo=0, sync type=digital separate, vsync+=1, hsync+=1
edid[71] = 0x1E
# Descriptors 2-4: monitor range + name (filled with dummy monitor descriptor)
for base in (72, 90, 108):
    edid[base:base+18] = [0x00,0x00,0x00,0xFD,0x00,0x18,0x4B,0x0F,0x46,0x11,0x00,0x0A,0x20,0x20,0x20,0x20,0x20,0x20]
# Extension count: 0
edid[126] = 0x00
# Checksum
edid[127] = (0x100 - sum(edid[:127])) & 0xFF

path = "/tmp/tc358743-1080p25.edid"
with open(path, "wb") as f:
    f.write(bytes(edid))
print(f"EDID written to {path}")
PYEOF
    v4l2-ctl --device="$DEVICE" --set-edid=file=/tmp/tc358743-1080p25.edid --fix-edid-checksums
fi

# Wait a moment for source to re-read EDID and send signal
sleep 2

# Set capture format: 1920x1080 UYVY @ 25fps (change framerate= for NTSC 30fps)
v4l2-ctl --device="$DEVICE" \
    --set-fmt-video=width=1920,height=1080,pixelformat=UYVY || \
v4l2-ctl --device="$DEVICE" \
    --set-fmt-video=width=1920,height=1080,pixelformat=BGR3

# Enable HDMI receiver (some driver versions require this)
v4l2-ctl --device="$DEVICE" --set-ctrl=enable_hdmi_rx=1 2>/dev/null || true

echo "tc358743: init complete"
echo "tc358743: current format:"
v4l2-ctl --device="$DEVICE" --get-fmt-video

echo "tc358743: input status:"
v4l2-ctl --device="$DEVICE" --query-dv-timings 2>/dev/null || true
