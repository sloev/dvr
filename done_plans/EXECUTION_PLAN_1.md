# Execution Plan

## 🤖 AI Directives (For Autonomous Execution)
**IMPORTANT INSTRUCTIONS FOR AGY (The AI):**
You have been invoked via `yolo` (`agy --dangerously-skip-permissions`). You are expected to operate **fully autonomously** to complete this entire plan. 
1. **Zero User Prompting:** Do NOT stop to ask the user for permission, input, or confirmation. Make technical decisions on your own.
2. **Execute Sequentially:** Start with Phase 1 (OS Build & CI/CD). Write the actual bash scripts, Dockerfiles, and GH Action YAMLs. Then move on to Phase 2.
3. **Commit & Push:** Use `git` to commit your work and push it to the remote repository.
4. **Self-Correction:** If you encounter errors (e.g., in CI or compilation), use your tools to read the error logs, fix the code, and try again. Do not give up or ask the user to fix it.
5. **Completion:** Only stop when both phases are implemented, committed, and pushed.
## Phase 1: Alpine OS Build & Dependency Pipeline

**Goal:** Create a reproducible script to generate a customized Alpine Linux aarch64 image for the Raspberry Pi with all required dependencies pre-installed and configured.

### 1. Build Script Development (`build_os.sh`)
- Set up a build environment (can use Docker with `alpine:latest` to build the image).
- Use `alpine-make-rootfs` or Alpine's `mkimage` to bootstrap an Alpine aarch64 rootfs.
- Inject the necessary system packages into the rootfs (from Edge/main and Edge/community):
  - `linux-rpi`, `raspberrypi-bootloader`
  - `v4l-utils`, `libdrm`, `mesa-egl`, `mesa-gles`, `mesa-gbm`, `mesa-dri-gallium`
  - GStreamer stack: `gstreamer`, `gst-plugins-base`, `gst-plugins-good`, `gst-plugins-bad`
  - Input: `libinput`, `eudev`
  - App deps: `rust`, `cargo`, `pkgconf`, `fontconfig-dev`
- Inject boot configuration (`/boot/config.txt` and `cmdline.txt`):
  - Add `dtoverlay=vc4-kms-v3d` and `dtoverlay=tc358743`.
- Configure system services:
  - Enable `udev`, `modules`, `sysfs`, and `devfs` in OpenRC.
  - Create init scripts to initialize the CSI-2 bridge (setting EDID and format) before app launch.
- Package the rootfs into a flashable `.img` file (with FAT32 boot partition and ext4 root partition).

### 2. GitHub Actions CI/CD (`.github/workflows/build-os.yml`)
- Create a workflow triggered on `push` to `main` or via manual `workflow_dispatch`.
- Environment: `ubuntu-latest` with QEMU/binfmt set up for aarch64 cross-building (if required).
- Steps:
  - Checkout repository.
  - Run `build_os.sh` inside a privileged Docker container.
  - Compress the output `.img` file.
  - Upload the resulting image as an artifact.
  - On tagged releases, publish the image to GitHub Releases automatically.

---

## Phase 2: DVR Application Development (Rust + Slint + KMS/DRM)

**Goal:** Build the DVR application leveraging hardware-accelerated video rendering and encoding.

### 1. Basic UI and KMS/DRM Integration
- Initialize a new Rust project (`cargo new dvr_app`).
- Set up Slint UI framework for the frontend.
- Implement KMS/DRM backend initialization in Rust to allow Slint to render directly to the screen (using EGL/GBM) without X11 or Wayland.
- Verify touch input processing via `libinput`.

### 2. GStreamer Pipeline Setup (Live Preview)
- Integrate `gstreamer-rs` (Rust bindings for GStreamer).
- Construct the base pipeline: capture `/dev/video0` -> zero-copy render to screen via `kmssink` (or overlay over Slint).
- Handle HDMI hot-plug events and adjust pipeline states.

### 3. Video Recording and Muxing
- Add the `tee` element to the pipeline to split the feed.
- Implement the recording branch: `tee -> queue -> v4l2h264enc -> h264parse -> mp4mux -> filesink`.
- Add file management logic in Rust (auto-segmentation, rotating logs/videos when disk is full).

### 4. UI Polish and Application Logic
- Connect Slint UI buttons to GStreamer pipeline controls (Record, Stop, Play).
- Add on-screen indicators (storage available, recording state, FPS).
- Test memory leaks and stability for long-running DVR behavior.

### 5. Final Integration
- Add the compiled `dvr_app` binary to the OS build script payload so the OS image boots directly into the DVR app.
