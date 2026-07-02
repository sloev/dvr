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

## 📝 TO-DO: Finalizing OS & DVR Features
- [ ] **I2S Audio Capture (HDMI):** Integrate `alsasrc` (I2S from tc358743) into the GStreamer pipeline and multiplex it with the H264 video into the `.mp4`.
- [ ] **Metadata Markers:** Inject `markers.txt` events directly into the MP4 file metadata (e.g. GStreamer Tags/Chapters) during recording.
- [ ] **Boot Graphics / Logo:** Configure the OS to display a custom splash screen (e.g. `fbsplash` or drawing to `/dev/fb0`) during boot to hide console text.
- [ ] **Full CI/CD Pipeline:** Ensure GitHub Actions correctly packages the `.img` and builds the Rust app reliably.
- [ ] **Documentation & Assets:** Write a comprehensive `README.md`, include UI screenshots, and structure the GitHub page.
- [ ] **Audio Meters & UI:** Display visual audio meters (PPM/VU) in the Slint UI.
- [ ] **Stopmotion Mode:** Capture individual frames, show onion skinning, and compile to `.mp4`.
- [ ] **On-Device Playback:** Browse recordings and play them back (e.g. via `mpv` overlay).
- [ ] **Wi-Fi Client Mode & OSK:** Scan networks, show On-Screen Keyboard, and connect as client.
- [ ] **Capture Settings:** Change resolution and framerate dynamically (restarting pipeline).
