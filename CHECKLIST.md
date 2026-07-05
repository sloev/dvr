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
- [x] **Stopmotion Mode:** Capture individual frames, show onion skinning, and compile to `.mp4`.
    - [x] Add Slint UI state for Stopmotion overlay.
    - [x] Rust logic to save individual `stopmo_0001.jpg` frames.
    - [x] Rust logic to invoke GStreamer/FFmpeg to compile JPEG sequence to MP4.
- [x] **On-Device Playback:** Browse recordings and play them back (e.g. via `mpv` overlay).
    - [x] Create basic Slint UI state for selecting a video file (Gallery).
    - [x] Implement Rust backend to pause/stop camera pipeline and launch playback using GStreamer `playbin` with `kmssink`.
    - [x] Restore main camera pipeline after playback.
- [x] **Wi-Fi Client Mode & OSK:** Scan networks, show On-Screen Keyboard, and connect as client.
    - [x] Create basic Slint UI for entering Wi-Fi SSID and Password.
    - [x] Implement Rust backend to generate `wpa_supplicant.conf` and connect.
- [x] **Capture Settings:** Change resolution and framerate dynamically.
    - [x] Add basic Slint UI for capture settings overlay.
    - [x] Implement Rust backend to apply capture settings.
- [x] **Multiple Stopmotion Projects:** Ensure multiple stopmotion projects can exist simultaneously (e.g., using separate folders per project).
- [x] **Automated UI Screenshots:** Update CI to automatically generate screenshots of all user stories and embed them in the documentation during the release/docs refresh.
- [x] **Fix CI "exec format error":** Add `setup-qemu-action` to `test-app` and `build-app` jobs so they can run `linux/arm64` Alpine containers on the x86_64 runners.

## ✅ DONE: Consolidated Polish Pass
- [x] **Wi-Fi Mode Hardening:** Replaced hardcoded demo credentials with Slint `LineEdit` inputs for SSID/password, wired to a testable `write_wifi_config` helper.
- [x] **UI Aesthetics:** Applied an 80s/90s "hackerman" retro theme (neon green on black, glowing borders, slide-in animations).
- [x] **Gallery Navigation:** Added a scrollable Gallery Grid UI that reads `/mnt/dvr_storage/`, lists recordings, and plays the selected file.
- [x] **`/gallery` HTTP endpoint authentication:** Added HTTP Basic Auth (`GALLERY_PASSWORD` env var) to prevent unauthenticated access to recorded media.
- [x] **Storage perf:** Reused a single `RealStorageSystem` across telemetry ticks instead of recreating it every second, and switched to `sort_by_cached_key` to avoid redundant `stat` syscalls when sweeping old recordings.
- [x] **Test coverage:** Added unit tests for `create_storage_dirs`, `setup_stopmotion_dir`, and `write_wifi_config`.

## ✅ DONE: Full Repo Audit Fixes
- [x] **CI/CD actually builds:** `test-app`/`build-app` were missing `eudev-dev`, `libinput-dev`, `libdrm-dev`, `mesa-dev`, `seatd-dev`, `libxkbcommon-dev` needed by Slint's `backend-linuxkms` feature, so every recent CI run failed after ~2 hours of QEMU-emulated compilation. Also dropped the `restore-keys` cache fallback that was masking the breakage with a stale `test-app` cache hit.
- [x] **Screenshots auto-publish to README + Pages:** `docs` job now commits the freshly generated `public/screenshots/*.png` back into `screenshots/` on the branch (`[skip ci]`) so GitHub's own README rendering shows real images, not just the Pages copy.
- [x] **Wi-Fi client config now actually works on hardware:** it was writing to `/etc/wpa_supplicant`, which is read-only on the target device per `build_os.sh`'s fstab - switched to `/run/wpa_supplicant` (tmpfs). Also escaped quotes/newlines to close a config-injection path, and the UI now reports real failures instead of always claiming "Connected to Wi-Fi".
- [x] **Record button no longer crashes the app** on a pipeline state-change failure (e.g. camera unplugged) - shows a notification instead of panicking on the UI thread. Same treatment for stopmotion frame capture I/O errors.
- [x] **Gallery playback no longer corrupts recordings or silently starts one:** it now EOS-finalizes the active recording before interrupting it for playback, and only resumes the camera pipeline afterward if it was actually recording before.
- [x] **Format USB requires confirmation** via a new overlay instead of wiping storage on a single tap.
- [x] **Gallery thumbnails are real:** generated (and cached, with orphan cleanup) via a short GStreamer decode pipeline instead of pointing at a placeholder file that never existed. "Newest first" now sorts by actual file mtime instead of filename, which previously misordered `dvr_*` vs `stopmo_proj_*` recordings.
- [x] **No more weak default credentials:** `GALLERY_PASSWORD` now generates and persists a random password (surfaced once in the UI) instead of defaulting to `"password"`, and `build_os.sh` generates a random per-device Wi-Fi AP passphrase at first boot instead of baking a fixed `dashcam_wifi` literal into every image. Also dropped deprecated `wpa_pairwise=TKIP` from the AP config.
- [x] **CI/CD build-os fixed end-to-end:** found and fixed, one real-CI-run at a time, three separate bugs blocking the OS image assembly stage that had never previously run to completion: `alpine-make-rootfs` doesn't have an `--arch` flag in the pinned version, the outer container was missing `f2fs-tools`, and (see below) board-specific capture tuning.
- [x] **Two board-tuned OS images:** `build-os` is now a matrix producing `dvr_alpine_aarch64_pi4_*` (BCM2711/VideoCore VI, full 1080p30) and `dvr_alpine_aarch64_pi2-3_*` (BCM2837/VideoCore IV - Pi 2 **v1.2 only** + Pi 3, conservative 720p30 default). Same compiled binary and rootfs either way; `dvr_app` reads `DVR_CAPTURE_WIDTH/HEIGHT/FPS/BITRATE` from `/etc/dvr_app.env` (written per-board by `build_os.sh`) so no separate build is needed per board. Neither variant has been validated on physical hardware.

## ✅ DONE: Rolling Releases
- [x] **Auto-incrementing rolling releases:** Dropped the `tags: 'v*'` trigger and manual-tag requirement. The `release` job now runs `if: github.ref == 'refs/heads/master' || 'refs/heads/main'`, same as `docs`, so every push to `master` (including merged PRs) builds both board images and publishes a new GitHub Release automatically. Version is `v0.1.<run_number>` - unique and monotonically increasing per workflow run, no `git tag` push needed since `softprops/action-gh-release` creates the tag itself when `tag_name` doesn't already exist. Added `generate_release_notes: true` for an auto-populated changelog per release.
- [x] **Fixed the release job silently skipping on tag pushes:** root-caused why the manually-created `v0.1.0` release never got its assets attached - the tag happened to point at the `docs` job's `[skip ci]` screenshot-refresh commit, and GitHub's skip-ci detection applies to any ref (branch or tag) that resolves to a `[skip ci]` commit, so the tag push never even triggered a workflow run. Recovered `v0.1.0` via a manual `workflow_dispatch` against that tag ref; moving to rolling releases (tied to the triggering commit, not a later manually-created tag) avoids this class of bug going forward.
- [x] **`main_ui.png` screenshot was a blank black image:** the "hackerman" neon-green theme was implemented correctly all along (confirmed via the other five screenshots), but `generate_screenshots.sh` captured `main_ui` - the very first `slint-viewer` launch on a cold runner - after a fixed 3s sleep, before Xvfb/Mesa's software-rasterizer shader cache/font atlas had finished warming up, so it snapshot a still-blank window. Every later capture reused those now-warm on-disk caches and rendered fine. Fixed by giving just that first capture an 8s warm-up instead of 3s.
- [x] **GitHub Pages was never actually deploying:** the `docs` job used `peaceiris/actions-gh-pages@v4`, which force-pushes to the `gh-pages` git branch - the "Deploy from a branch" mechanism. This repo's Settings -> Pages -> Source is set to "GitHub Actions" instead, so every one of those pushes was silently inert; the live site kept serving whatever an old, unrelated workflow (from this project's original "RETRO DVR" prototype) last deployed via the real Actions-deployment API, days earlier. Fixed by switching the `docs` job to `actions/upload-pages-artifact` and adding a `deploy-pages` job using the official `actions/deploy-pages`, which is source-agnostic-correct for "Source: GitHub Actions".

## 🐛 Real-hardware bring-up (Pi 2 v1.2, DSI touchscreen)
- [x] **DSI touchscreen never lit up on real hardware:** first physical boot test (Pi 2 v1.2 + a DSI touchscreen, always the intended display) showed nothing at all on screen despite the board otherwise booting (SD activity LED behaved normally). `build_os.sh`'s `/boot/config.txt` set `dtoverlay=vc4-kms-v3d` and `dtoverlay=tc358743` (the HDMI *capture-input* chip) but never enabled DSI output itself - unlike HDMI, a DSI panel has no auto-negotiation protocol and needs `display_auto_detect=1` for the firmware to probe and turn one on at all. Recovered the correct config from this project's original "RETRO DVR" prototype (which targeted the same panel) and added `display_auto_detect=1` + `hdmi_force_hotplug=0`. Not yet re-validated on the reporter's actual hardware.
- [ ] **WiFi AP (`DVR_DASHCAM_AP`) not broadcasting on the same board**, tested via a USB WiFi dongle (Pi 2 has no onboard wireless) - not yet root-caused; likely candidates are an unsupported dongle chipset (no AP-mode-capable driver in Alpine's `linux-rpi` kernel) or a deeper service-startup issue, but this couldn't be diagnosed further while the board had zero visual output. Revisit once the DSI fix above gets the screen working, since the on-screen state will make this much easier to debug than guessing blind.
