# DVR Project Plan

## Step 1: Base OS and Dependencies (Alpine Linux)

### 1. OS Installation & Boot Configuration
- **Base Image:** Alpine Linux for Raspberry Pi (aarch64).
- **Firmware & Kernel:** Use `linux-rpi` for optimal hardware support.
- **Boot Config (`/boot/config.txt`):**
  - Enable GPU/DRM: `dtoverlay=vc4-kms-v3d`
  - Enable HDMI to CSI-2 Bridge (assuming standard Toshiba TC358743): `dtoverlay=tc358743`
  - Assign sufficient GPU memory (e.g., `gpu_mem=128` or more depending on Pi version, though `vc4-kms-v3d` uses dynamic memory allocation mostly).
  - Enable DSI display (usually auto-detected for official displays, or specific `dtoverlay` for third-party).

### 2. System Packages & Dependencies
*All packages verified for Alpine Linux (aarch64) in edge/main and edge/community repositories.*
- **Base OS & Kernel:** `linux-rpi` (Raspberry Pi specific kernel), `raspberrypi-bootloader` (firmware and bootloader).
- **Video Capture (V4L2):** `v4l-utils` to configure the CSI-2 bridge (resolution, framerate, EDID).
- **Hardware Acceleration:** `mesa-egl`, `mesa-gles`, `mesa-gbm`, `libdrm`, `mesa-dri-gallium` (Alpine bundles vc4/v3d drivers here).
- **Multimedia Processing:** `gstreamer`, `gst-plugins-base`, `gst-plugins-good`, `gst-plugins-bad` (for hardware encoding via `v4l2m2m`).
- **Input (Touch):** `libinput`, `eudev` (for device management).
- **Development (DVR App):** `rust`, `cargo`, `pkgconf`, `fontconfig-dev` (required to build the Slint UI).
- **Display Server/Compositor:**
  - Direct KMS/DRM: The application will run natively on KMS/DRM (Kernel Mode Setting / Direct Rendering Manager) utilizing EGL/GBM, without any intermediate compositor or Wayland/X11 server. This guarantees lowest latency and overhead.

### 3. System Configuration
- **udev Rules:** Assign correct permissions for `/dev/video*`, `/dev/dri/card*`, and `/dev/input/event*` to allow the DVR app to run without root.
- **EDID injection:** Load standard 1080p60 EDID into the HDMI-CSI2 bridge via `v4l-ctl` on boot.
- **Init Scripts:** Configure OpenRC services to auto-initialize the CSI-2 bridge on startup before launching the DVR app.

---

## Step 2: The DVR Application

### 1. Technology Stack
- **Language:** Rust (for memory safety, excellent concurrency, and strong ecosystem).
- **UI Framework:** Slint (https://docs.slint.dev/latest/docs/slint/). It supports direct rendering to KMS/DRM via EGL/GBM, making it perfect for an embedded Raspberry Pi UI without a display server.
- **Media Backend:** GStreamer. It excels at complex zero-copy pipelines (Capture -> Split -> (1) Display + (2) Encode to disk).

### 2. Application Architecture
- **GStreamer Pipeline:**
  - **Source:** `v4l2src device=/dev/video0` (CSI-2 input).
  - **Tee (Splitter):** Splits the stream into two branches.
  - **Branch 1 (Live Preview):** Uses `kmssink` (or GStreamer rendering into Slint's OpenGL context) for hardware-accelerated, zero-copy rendering to the DSI screen alongside the UI.
  - **Branch 2 (Recording):** Uses `v4l2h264enc` (hardware H.264 encoder on the Pi GPU) -> `h264parse` (required to extract NAL units and stream metadata from the raw H.264 byte-stream for the container) -> `mp4mux` (packages the stream into an MP4 container) -> `filesink`.
- **UI Overlay:** 
  - Rendered over the video preview. 
  - Handles touch events via `libinput`/framework integration.
  - UI Elements: Record button, status indicator (disk space, resolution, FPS), playback gallery.

### 3. Core Features
- **Live Monitoring:** Real-time, low-latency display of the HDMI input.
- **DVR Controls:** Tap-to-record, tap-to-stop.
- **Storage Management:** Auto-segmentation of video files, continuous loop recording (deleting oldest files when full).
- **Hardware Integration:** Graceful shutdown button, hot-plug detection for the HDMI input source.
