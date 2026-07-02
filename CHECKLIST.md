# DVR Feature Checklist

## ✅ DONE
- [x] OS Build Script (`build_os.sh`) with Alpine aarch64, read-only root, and hardware dependencies.
- [x] GitHub Actions CI/CD Pipeline.
- [x] Base Rust Application structure (Cargo, `build.rs`).
- [x] Hardware-Accelerated GStreamer Pipeline (zero-copy KMS preview, `v4l2h264enc` encoding).
- [x] Splitmuxsink for continuous loop recording and file segmentation.
- [x] Automated Ring-Buffer Storage (sweeps old recordings when > 90% full).
- [x] Base Slint UI with Telemetry (CPU, RAM, Disk, FPS) and Record/Stop logic.
- [x] Basic AP Mode Wi-Fi Setup (`hostapd`, `dnsmasq`).
- [x] Embedded HTTP Server (Axum) for downloading files over Wi-Fi.

## ✅ DONE (From Old Codebase Migration)
- [x] **Capturing Stills:** Added UI button and stub integration to save to `stills/`.
- [x] **Timeline Markers:** Added UI button to save timestamps to `markers.txt`.
- [x] **USB Formatting:** Added UI button to format `/mnt/dvr_storage` to F2FS.
- [x] **Safe Eject:** Added UI button to safely unmount `/mnt/dvr_storage`.
- [x] **System Power Management:** Added UI button to gracefully `poweroff`.
- [ ] **Stopmotion Mode:** Capture individual frames, show onion skinning, and compile to `.mp4`.
- [ ] **On-Device Playback:** Browse recordings and play them back (e.g. via `mpv` overlay).
- [ ] **Wi-Fi Client Mode & OSK:** Scan networks, show On-Screen Keyboard, and connect as client.
- [ ] **Capture Settings:** Change resolution and framerate dynamically (restarting pipeline).
- [ ] **Audio Meters & Capture:** Capture audio, show visual meters, switch between PPM/VU.

