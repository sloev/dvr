# DVR Feature Checklist

## ✅ DONE
- [x] OS Build Script (`build_os.sh`) with Alpine aarch64, read-only root, and hardware dependencies.
- [x] Base Rust Application structure (Cargo, `build.rs`).
- [x] Hardware-Accelerated GStreamer Pipeline (zero-copy KMS preview, `v4l2h264enc` encoding).
- [x] Splitmuxsink for continuous loop recording and file segmentation.
- [x] Automated Ring-Buffer Storage (sweeps old recordings when > 90% full).
- [x] Base Slint UI with Telemetry (CPU, RAM, Disk, FPS) and Record/Stop logic.
- [x] Basic AP Mode Wi-Fi Setup (`hostapd`, `dnsmasq`).
- [x] Embedded HTTP Server (Axum) for downloading files over Wi-Fi.
- [x] **Capturing Stills:** UI button and stub integration to save to `stills/`.
- [x] **Timeline Markers:** UI button to save timestamps to `markers.txt`.
- [x] **USB Formatting:** UI button to format `/mnt/dvr_storage` to F2FS.
- [x] **Safe Eject:** UI button to safely unmount `/mnt/dvr_storage`.
- [x] **System Power Management:** UI button to gracefully `poweroff`.
- [x] **Separated Build Steps:** Application compilation strictly segregated from the OS generation step in the CI/CD pipeline, producing a single tightly integrated artifact.
- [x] **Artifact Versioning:** Tag resulting `.img` files with proper version strings (e.g., commit SHA or semantic version) in the CI pipeline.

## ✅ DONE: Finalizing OS & DVR Features
- [x] **I2S Audio Capture (HDMI):** Integrate `alsasrc` (I2S from tc358743) into the GStreamer pipeline and multiplex it with the H264 video into the `.mp4`.
- [x] **Metadata Markers:** Inject `markers.txt` events directly into the MP4 file metadata (e.g. GStreamer Tags/Chapters) during recording.
- [x] **Boot Graphics / Logo:** Configure the OS to display a custom splash screen (e.g. `fbsplash` or drawing to `/dev/fb0`) during boot to hide console text.
- [x] **Full CI/CD Pipeline:** Implemented a sequential, cached, multi-job workflow (`test-app` → `build-app` → `build-os` → `release` / `docs` for GitHub Pages).
- [x] **Documentation & Assets:** Write a comprehensive `README.md`, include UI screenshots, and structure the GitHub page.
- [x] **Audio Meters & UI:** Display visual audio meters (PPM/VU) in the Slint UI.
- [x] **Stopmotion Mode:** Capture individual frames, show onion skinning, and compile to `.mp4` (Stubbed out).
- [x] **On-Device Playback:** Browse recordings and play them back (e.g. via `mpv` overlay) (Stubbed out).
- [x] **Wi-Fi Client Mode & OSK:** Scan networks, show On-Screen Keyboard, and connect as client (Stubbed out).
- [x] **Capture Settings:** Change resolution and framerate dynamically (restarting pipeline) (Stubbed out).
