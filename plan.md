# DVR Build Plan — RPi Bullseye 32-bit HDMI Capture Device

## Target hardware
| Component | Part |
|-----------|------|
| SBC | Raspberry Pi (3B+/4/CM4) — Bullseye 32-bit |
| Capture | HDMI→CSI-2 C790 (Toshiba TC358743XBG) |
| Display | iPistBit DSI 800×480 capacitive touchscreen |
| Storage | USB drive (FAT32/exFAT) for recordings |
| Audio | I2S from TC358743 board → RPi I2S header |
| Input source | Hi8 camera → CVBS→HDMI upscaler → capture card |

## Use case
Lofi DIY Atomos-style field recorder. Plug in a Hi8 (or any HDMI source), hit REC, recordings land on USB. Minimal UI overlaid on live preview, all touch-controlled via DSI screen.

---

## Steps

### Step 1 — SD card boot config (`/boot/config.txt`)
- Enable `dtoverlay=tc358743` for CSI-2 capture
- Enable `dtoverlay=vc4-kms-v3d` (KMS/DRM, needed for modern GStreamer sinks)
- Disable camera auto-detect that conflicts with tc358743
- Enable I2S overlay for audio from capture board
- Enable DSI display (usually auto-detected; add rotation if needed)
- Set GPU memory split (128 MB minimum for hardware encoding)
- Disable overscan, enable HDMI hotplug passthrough

### Step 2 — Kernel cmdline (`/boot/cmdline.txt`)
- Prepare the `ro` (read-only root) flag
- Add `fsck.mode=skip` for fast boot
- Add `quiet splash` for clean startup

### Step 3 — First-boot install script (`setup/install.sh`)
Runs once as root from a writable SD to install all dependencies:
- `gstreamer1.0-*` plugins (base, good, bad, alsa, x) — no libav/ugly/gl needed (hardware encoder + voaacenc)
- `v4l-utils` for TC358743 EDID injection and format negotiation
- `python3-gi` (GObject introspection for GStreamer in Python)
- `python3-tk` (Tkinter — Python stdlib UI, no Qt needed)
- GStreamer `xvimagesink` embeds into a `tk.Frame` XID — same GPU-overlay pattern as `picamera.start_preview()`
- `alsa-utils`, `libasound2-dev`
- `network-manager`, `nmcli` for WiFi
- `udisks2` for safe USB eject
- Fonts (lightweight monospace/sans for UI)
- Disable unneeded services (bluetooth, avahi, etc.)

### Step 4 — Read-only SD card (`setup/readonly.sh`)
- Use `overlayroot` or manual `overlayfs` to make `/` read-only
- Mount `/tmp` and `/var/log` as tmpfs
- Keep `/boot` read-only (remount rw only when updating config)
- Create `/etc/overlayroot.conf`
- USB mount point stays writable (separate partition/device)

### Step 5 — TC358743 EDID + format setup (`setup/tc358743.sh`)
- Runs as a oneshot systemd service before the app starts
- Injects a 1080p25/30 EDID binary into the TC358743 via `v4l2-ctl --set-edid`
- Sets the capture format: `v4l2-ctl --set-fmt-video=width=1920,height=1080,pixelformat=UYVY`
- Enables HDMI RX on the device

### Step 6 — ALSA / I2S audio config (`setup/asound.conf`)
- Configure the TC358743 I2S output as ALSA capture device `hw:1,0`
- Set 48000 Hz, stereo, S32_LE (typical for TC358743 I2S)
- Create a dmix/dsnoop setup so preview monitoring and recording share the device

### Step 7 — WiFi pre-seed (`setup/wpa_supplicant.conf`)
- Template `wpa_supplicant.conf` for initial WiFi setup from SD card
- App manages additional networks at runtime via `nmcli`

### Step 8 — Application source (`src/`)
Python application using PyQt5 + GStreamer:

#### `src/pipeline.py` — GStreamer pipeline manager
- **Preview pipeline**: `v4l2src → video/x-raw(UYVY,1920×1080) → tee → [xvimagesink into Qt widget] + [queue → fakesink]`
- **Single pipeline**, two tees (`vtee`/`atee`) so the single-open V4L2 and I2S devices feed both preview and record. NO second process/pipeline.
- **Record branch** (added to the tees on demand, as one Gst.Bin): `queue → v4l2convert (HW UYVY→I420) → v4l2h264enc (HW) → h264parse → mp4mux ← (queue → audioconvert → audioresample → voaacenc → aacparse)` → `filesink`
- Start = add bin + request tee pads; Stop = block tee pads, inject EOS, wait for filesink EOS (so the MP4 moov atom is written), then remove bin
- Clip splitting via a 30-min timer that finalizes the current clip and starts the next

#### `src/storage.py` — USB storage manager
- Poll `udev` / `/proc/mounts` for USB drives
- Mount on detect, expose path to recorder
- Safe eject via `udisksctl power-off`
- Calculate free space

#### `src/wifi.py` — WiFi manager
- Wrap `nmcli` for scan, connect, forget, list known networks
- Persist networks (survives read-only root because NetworkManager state lives on USB or tmpfs-backed overlay)

#### `src/system.py` — System helpers
- Shutdown: `systemctl poweroff`
- Reboot: `systemctl reboot`
- Remount `/boot` rw for config edits
- Read CPU temp, uptime

#### `src/app.py` — Tkinter UI (replaces PyQt5)
- `main_window.py`: Fullscreen QMainWindow, no title bar, black bg; embeds GStreamer preview via `XEmbedVideoWidget`; routes touch to overlay
- `overlay.py`: Transparent QWidget stack on top of video:
  - **Top bar**: timecode, input signal indicator (green/red), clip name, audio level meters (L/R vu bars)
  - **Bottom bar**: REC / STOP button, free space bar, USB status pill, power button
  - **Left swipe panel**: WiFi networks list, connect/forget
  - **Right swipe panel**: Playback file browser, thumbnail list of recordings
  - **Center tap**: Show/hide chrome (clean preview mode)
- `playback.py`: Full-screen playback with scrub bar, rendered via GStreamer `playbin`
- `settings.py`: Simple settings sheet (resolution, clip length, display brightness)

#### UI design language
- Palette: near-black (#0d0d0d) panels, #e0e0e0 text, #e03030 record red, #30e030 signal green
- Font: Monospace 13pt for timecodes, Sans 14pt for labels
- No shadows, no animations — flat, instant transitions
- All touch targets ≥ 48×48 px

### Step 9 — Systemd services (`systemd/`)
- `tc358743.service`: oneshot, runs EDID script before app
- `dvr.service`: starts the Python app, `After=tc358743.service graphical.target`, `Restart=always`
- Both installed to `/etc/systemd/system/`

### Step 10 — Autostart wiring
- Disable unnecessary services (lightdm optional — use `xinit` or Wayland direct)
- `dvr.service` targets graphical session
- If using X11: `/etc/X11/Xsession` or `.xinitrc` launches app; systemd starts `xinit` via a getty override

### Step 11 — Read-only finalization
- After install, re-enable read-only overlay
- Test cold boot: EDID service → app launch → preview live
- Verify USB write path works while SD is read-only

---

## Feature list (lofi Atomos DVR)

| Feature | Implementation |
|---------|---------------|
| Live 1080p preview | GStreamer v4l2src → xvimagesink |
| Hardware H.264 encode | v4l2h264enc (RPi BCM codec) |
| Stereo audio record | alsasrc I2S → voaacenc → mp4mux |
| Auto clip split | 30-min segments, seamless |
| USB record & eject | udisks2 + udev |
| Playback browser | GStreamer playbin, file list |
| WiFi manager | nmcli wrapper |
| Signal indicator | v4l2 input status poll |
| Audio level meters | GStreamer level element |
| Timecode overlay | in-app (wall clock + rec duration) |
| Read-only SD | overlayfs |
| Shutdown button | systemctl poweroff |
| Auto-start | systemd dvr.service |
| Input info HUD | resolution, framerate, format |
| Scene markers | keypress → append timestamps.txt on USB |
| Loop record mode | ring buffer, configurable total size |
| Quick USB format | mkfs.exfat via subprocess |
| CPU temp display | /sys/class/thermal/thermal_zone0/temp |

---

## File tree (this repo)
```
dvr/
├── plan.md                  ← this file
├── setup/
│   ├── config.txt           ← /boot/config.txt
│   ├── cmdline.txt          ← /boot/cmdline.txt
│   ├── install.sh           ← run once on first writable boot
│   ├── readonly.sh          ← enable overlayfs RO root
│   ├── asound.conf          ← /etc/asound.conf
│   ├── tc358743.sh          ← EDID injection + format set
│   ├── tc358743-1080p25.edid← raw EDID binary
│   └── wpa_supplicant.conf  ← seed WiFi on first boot
├── src/
│   ├── main.py
│   ├── pipeline.py
│   ├── storage.py
│   ├── wifi.py
│   ├── system.py
│   └── ui/
│       ├── __init__.py
│       ├── main_window.py
│       ├── overlay.py
│       ├── playback.py
│       └── settings.py
├── systemd/
│   ├── tc358743.service
│   └── dvr.service
└── deploy.sh                ← copies files to mounted SD card
```

---

## Deployment
1. Flash Bullseye Lite to SD card
2. Mount SD boot + root partitions
3. Copy `setup/config.txt` → `/boot/config.txt`
4. Copy `setup/cmdline.txt` → `/boot/cmdline.txt`
5. Copy `setup/wpa_supplicant.conf` → `/boot/wpa_supplicant.conf` (RPi copies on first boot)
6. Enable SSH: `touch /boot/ssh`
7. Boot RPi, SSH in, run `sudo bash /boot/install.sh` (copy it there too)
8. Run `sudo bash /boot/readonly.sh` to lock SD
9. Done — subsequent boots are fully self-contained
