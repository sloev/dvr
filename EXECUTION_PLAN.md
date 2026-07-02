# Execution Plan: Fully Feature-Compatible DVR System

This document outlines a hyper-detailed, step-by-step master plan to build a production-grade, highly resilient DVR system natively running on a customized Alpine Linux OS for aarch64 (Raspberry Pi/similar SOCs), with a Rust-based, hardware-accelerated DVR application.

## 🤖 AI Directives (For Autonomous Execution)
**IMPORTANT INSTRUCTIONS FOR AGY (The AI):**
You are expected to operate **fully autonomously** to complete this entire plan.
1. **Zero User Prompting:** Do NOT stop to ask the user for permission, input, or confirmation. Make all technical decisions on your own based on best practices.
2. **Execute Sequentially:** Start with Phase 1 and proceed step-by-step.
3. **Commit & Push:** After each major phase, use `git` to commit your work and push it to the remote repository.
4. **Self-Correction:** If you encounter errors, read the logs, fix the code, and retry autonomously.

---

## User Stories & Target Features
**User Stories:**
- As a driver, I want the DVR to boot immediately when my car starts so I never miss recording an event.
- As a driver, I want the UI to give me a live preview with hardware acceleration so the system doesn't lag or overheat.
- As a driver, I want the system to manage its own storage automatically so I don't have to worry about the SD card getting full and stopping recording.
- As a user, I want the file system to be read-only (except for the storage drive) so sudden power loss when the car turns off doesn't corrupt my OS.
- As a user, I want to be able to connect to a WiFi hotspot hosted by the DVR to download clips directly to my smartphone without removing the SD card.

**Key Features:**
- **Instant Boot:** Extremely fast, clean boot without text logs, directly into the UI.
- **Resilient OS:** Read-only root filesystem on Alpine Linux.
- **Hardware Acceleration:** Zero-copy KMS/DRM rendering and V4L2 H264 hardware encoding.
- **Continuous Loop Recording:** Seamless video segmentation and auto-deletion of oldest files when storage hits 90%.
- **Modern Touch UI:** Slint-based dashboard displaying live preview, FPS, CPU usage, and recording status.
- **Wireless Retrieval:** Built-in WiFi Access Point and Axum-based HTTP server for mobile video downloads via QR code.

---

## Phase 1: Robust Alpine Linux OS Construction (aarch64)

**Objective:** Build a resilient, read-only host OS tailored specifically for continuous DVR operation, minimizing SD card wear and ensuring bulletproof boot cycles.

### Step 1.1: Advanced Build Script Setup (`build_os.sh`)
- Utilize `alpine-make-rootfs` within a privileged Docker container (via QEMU aarch64).
- Inject all necessary packages: `linux-rpi`, `raspberrypi-bootloader`, `v4l-utils`, `libdrm`, `mesa-egl`, `gstreamer`, `gst-plugins-base/good/bad/ugly`, `libinput`, `eudev`, `openrc`, `rust`, `cargo`.
- Configure the OS layout with 3 partitions:
  - `boot` (FAT32, 500MB)
  - `rootfs` (Ext4, 1.5GB, mounted read-only)
  - `storage` (F2FS or Ext4, remaining space, mounted read-write for DVR recordings)

### Step 1.2: Boot and Hardware Configuration
- Configure `/boot/config.txt` to enable hardware overlays: `dtoverlay=vc4-kms-v3d`, `dtoverlay=tc358743` (for HDMI to CSI-2 capture), `gpu_mem=256`.
- Set `/boot/cmdline.txt` for minimal boot output (`quiet loglevel=1 vt.global_cursor_default=0`) to achieve a seamless, clean boot.
- Implement a custom splash screen (e.g., using `fbsplash` or drawing a raw image to `/dev/fb0`) to mask the boot logs.

### Step 1.3: Init System and Read-Only Root (`/etc/fstab` & OpenRC)
- Map the root partition to mount as `ro` (read-only) in `/etc/fstab`.
- Map `/var/log`, `/tmp`, and `/run` to `tmpfs` RAM disks to avoid writing temporary files to the SD card.
- Mount the `storage` partition to `/mnt/dvr_storage` automatically.
- Register OpenRC runlevels to auto-start `udev`, load V4L2/DRM modules, initialize the camera bridge settings via `v4l2-ctl`, and launch the DVR application as a dedicated service without invoking a TTY login prompt.

---

## Phase 2: Core DVR App Foundation (Rust + Slint + KMS/DRM)

**Objective:** Develop a robust, hardware-accelerated Rust application capable of handling high-speed video pipelines and direct-to-screen UI rendering.

### Step 2.1: Project Initialization & Cargo Setup
- Initialize the `dvr_app` Cargo workspace.
- Include dependencies: `gstreamer`, `slint` (with `linuxkms` feature), `tokio` (for async background tasks), `v4l`, `sysinfo` (for hardware monitoring).

### Step 2.2: Slint UI Integration (Direct DRM/KMS)
- Architect the `.slint` UI file with a rich, modern layout:
  - **Live Preview Container**: A transparent/blank area where the GStreamer video sink will render underneath the UI.
  - **Telemetry Dashboard**: Dynamic fields for Disk Usage (%), RAM Usage (%), CPU Load (%), and Current FPS.
  - **Controls**: Touch-friendly floating buttons for Record, Stop, and Settings/Gallery.
  - **Recording Indicator**: A pulsing red circle and timestamp when recording is active.
- Configure `slint::platform::set_platform` in Rust to force the LinuxKMS backend, listening directly to `libinput` for touch events.

---

## Phase 3: Hardware-Accelerated GStreamer Pipeline

**Objective:** Implement a zero-copy, highly efficient video processing pipeline for simultaneous live preview and file encoding.

### Step 3.1: V4L2 Video Capture and Splitting
- Initialize `gstreamer-rs`.
- Construct the base pipeline: `v4l2src device=/dev/video0 ! video/x-raw,format=UYVY,width=1920,height=1080,framerate=30/1 ! tee name=t`.

### Step 3.2: Live Preview Branch (Zero-Copy Display)
- Route the first branch of the `tee` to the screen: `t. ! queue max-size-buffers=2 drop=true ! kmssink force-modesetting=true plane-properties="..."`.
- Coordinate the `kmssink` plane configuration so the video renders on a DRM plane slightly behind the Slint UI plane, or configure colorkeying.

### Step 3.3: Hardware H264 Encoding Branch
- Route the second branch of the `tee` to the encoding module: `t. ! queue ! v4l2h264enc extra-controls="encode,video_bitrate=10000000" ! h264parse`.
- Use `splitmuxsink` to automatically segment the video files every 5 minutes (or 1GB), storing them in `/mnt/dvr_storage/` with timestamped filenames (e.g., `dvr_YYYYMMDD_HHMMSS.mp4`).

### Step 3.4: Dynamic Pipeline Controls and EOS Handling
- Bind the Slint UI "Record/Stop" buttons to dynamically link/unlink the recording branch from the `tee` using GStreamer Pad probes, avoiding interruptions to the live preview.
- Ensure correct End-Of-Stream (EOS) events are sent to the `splitmuxsink` before unlinking, to prevent corrupted MP4 headers.

---

## Phase 4: Storage Management & System Resilience

**Objective:** Guarantee that the DVR operates indefinitely without crashing due to full disks or memory leaks.

### Step 4.1: Automated Ring-Buffer Storage (Disk Sweeping)
- Spawn an asynchronous Tokio task in Rust that periodically (e.g., every 60 seconds) scans `/mnt/dvr_storage/`.
- If disk usage exceeds 90% (checked via `sysinfo`), locate the oldest `.mp4` file and delete it.
- Emit a UI signal to briefly display "Cleaning old records..." to the user.

### Step 4.2: Hardware Monitoring Telemetry
- Use the `sysinfo` crate to poll CPU utilization, RAM usage, and available storage bytes every second.
- Dispatch these metrics to the Slint UI thread to continuously update the on-screen dashboard.

### Step 4.3: Fault Tolerance & Watchdog
- Implement a Rust panic handler to log crashes to `/mnt/dvr_storage/crash.log`.
- Enable the hardware watchdog timer (`/dev/watchdog`) in Alpine OpenRC, ensuring the Raspberry Pi hard-reboots automatically if the OS or DVR app hangs completely.

---

## Phase 5: Connectivity & Media Retrieval

**Objective:** Allow users to effortlessly download their saved DVR clips without removing the SD card.

### Step 5.1: Network Setup (WiFi Access Point)
- Integrate `hostapd` and `dnsmasq` into the Alpine build script.
- Configure the Raspberry Pi to broadcast a dedicated WiFi network (e.g., `DVR_DASHCAM_AP`).

### Step 5.2: Embedded HTTP Server (Axum/Actix)
- Add a lightweight HTTP server thread directly within the Rust application (`axum` framework).
- Serve a simple, automatically generated HTML gallery listing all `.mp4` files in `/mnt/dvr_storage/`.
- Expose an endpoint (`/download/:filename`) enabling fast, direct downloads to smartphones connected to the WiFi AP.
- Add a QR code rendering mechanism in the Slint UI so users can scan it to instantly open the download gallery on their phone.

---

## Phase 6: Final CI/CD & Artifact Generation

**Objective:** Automate the entire process into a push-button deployment.

### Step 6.1: GH Actions Workflow Assembly
- Refine `.github/workflows/build-os.yml` to compile the Rust binary in a cross-compilation environment (or native `arm64` container).
- Trigger the OS packager to inject the compiled binary, generate the read-only file system, and output the `.img` file.
- Compress to `.img.gz` and attach it to GitHub Releases alongside SHA256 checksums.

### Step 6.2: End-to-End Validation
- Ensure all phases are integrated perfectly. The final result should be a single flashable image that, upon first boot, instantly launches into a gorgeous UI with a live camera feed, automatically managing its own storage and allowing WiFi downloads, forever.
