# DVR Application - Feature & User Story Matrix

Here is a comprehensive list of all implemented features and user stories in the DVR application, mapped out step-by-step to verify end-to-end support.

### 1. Recording Video
* **User Story:** As a user, I want to record live video to a connected USB drive.
* **Steps:**
  1. Insert USB drive -> App detects drive and mounts it ("◉ X GB" appears on action row).
  2. Press "● REC" on action row.
  3. Red border appears around UI, button changes to "■ STOP", and timecode elapsed timer starts.
  4. Press "■ STOP".
  5. Recording pipeline safely stops and saves the file to the USB drive.
* **Status:** ✅ Fully Supported

### 2. Capturing Stills (Photos)
* **User Story:** As a user, I want to capture a high-quality still frame from the live video feed while recording.
* **Steps:**
  1. Start a video recording.
  2. Press the "📷" (Grab) button that appears in the contextual slot.
  3. Image is captured and saved to the `stills/` directory on the USB drive.
  4. Green flash notification appears: "📷 saved".
* **Status:** ✅ Fully Supported

### 3. Placing Timeline Markers
* **User Story:** As a user, I want to place a marker during an active recording to easily find a specific moment later.
* **Steps:**
  1. Start a video recording.
  2. Press the "⊕" (Mark) button on the action row.
  3. App writes the absolute timestamp and relative elapsed time to `markers.txt` on the USB drive.
  4. Flash notification "⊕ marker" appears.
* **Status:** ✅ Fully Supported

### 4. Stopmotion Animation mode
* **User Story:** As a user, I want to capture individual frames and compile them into a stopmotion video sequence.
* **Steps:**
  1. Open Menu (☰) -> Tap "🎬 Stopmotion".
  2. App enters Stopmotion Mode and creates a new project directory (`stopmotion/proj_...`).
  3. Press "📷 CAPT" to capture individual frames.
  4. Press "🧅" to toggle Onion Skin (a transparent overlay of the previously captured frame).
  5. Press "+" or "-" to adjust the Onion Skin opacity.
  6. Press "🔁" to preview the recently captured frames as an animated loop.
  7. Press "🎬" on the action row to open the Compile Stopmotion dialog.
  8. Select desired framerate (e.g., 5, 8, 12, 24 FPS) and press "Compile".
  9. App generates an `.mp4` video from the frames and shows a success notification.
* **Status:** ✅ Fully Supported

### 5. Viewing and Managing Recordings
* **User Story:** As a user, I want to browse my saved video clips, play them back, and delete the ones I no longer need.
* **Steps:**
  1. Press "▶" (PLAY) on the action row.
  2. Playback panel slides in from the right, populating a list of `.mp4` clips from the USB drive.
  3. Select a clip and press "▶ Play" (or double-tap the clip).
  4. Clip plays fullscreen via the `mpv` hardware-accelerated media player.
  5. Select a clip and press "🗑 Delete".
  6. Confirm the deletion prompt -> Clip is permanently deleted from the USB drive.
  7. Press "↻" to refresh the list of available clips.
* **Status:** ✅ Fully Supported

### 6. Connecting to Wi-Fi
* **User Story:** As a user, I want to connect the device to a wireless network using the touchscreen.
* **Steps:**
  1. Open Menu (☰) -> Tap "📶 Wi-Fi".
  2. Wi-Fi panel slides in from the left.
  3. Press "↻ Scan" -> NetworkManager scans and populates a list of nearby SSIDs (showing signal strength and security status).
  4. Select a secured SSID -> The custom On-Screen Keyboard automatically slides up from the bottom.
  5. Type the network password -> Press "Submit" (or press "Connect").
  6. Background thread attempts connection.
  7. Status label updates to "Connected: [SSID] (XX%)".
* **Status:** ✅ Fully Supported

### 7. Configuring Capture Settings
* **User Story:** As a user, I want to change the video capture resolution and framerate to match my input source.
* **Steps:**
  1. Open Menu (☰) -> Tap "⚙ Settings".
  2. Settings dialog appears showing the current active resolution.
  3. Tap a resolution preset (e.g., "1920 × 1080", "1280 × 720", "720 × 576 PAL").
  4. Dialog closes, GStreamer pipeline is instantly reconfigured, and the setting is persistently saved for future reboots.
* **Status:** ✅ Fully Supported

### 8. Configuring Audio Meters
* **User Story:** As a user, I want to toggle between PPM (Peak Programme Meter) and VU (Volume Unit) audio ballistics.
* **Steps:**
  1. Open Menu (☰) -> Tap "⚙ Settings".
  2. Tap either "PPM" or "VU" under the Audio meters section.
  3. Dialog closes and the on-screen audio meters instantly change their attack/decay ballistics.
* **Status:** ✅ Fully Supported

### 9. Formatting USB Storage
* **User Story:** As a user, I want to wipe and format a newly inserted USB drive directly from the device UI.
* **Steps:**
  1. Insert USB drive.
  2. Open Menu (☰) -> Tap "⚙ Settings".
  3. Scroll down and press "Format USB" (Only visible when a drive is attached).
  4. Warning confirmation dialog appears ("ALL recordings will be deleted").
  5. Press "Format".
  6. "Formatting..." overlay blocks the UI.
  7. Formatting succeeds via `udisks2` -> "Format complete" overlay appears.
* **Status:** ✅ Fully Supported

### 10. Safely Ejecting USB
* **User Story:** As a user, I want to safely eject the USB drive to prevent filesystem corruption before unplugging it.
* **Steps:**
  1. Press the "⏏" (Eject) button on the action row.
  2. Confirmation dialog appears.
  3. Press "Eject".
  4. App automatically stops any active recordings safely.
  5. "Ejecting..." overlay appears -> Drive is unmounted via `udisksctl`.
  6. "✓ Safe to remove" overlay appears.
* **Status:** ✅ Fully Supported

### 11. Viewing System Info
* **User Story:** As a user, I want to see a diagnostic overview of the hardware and software state.
* **Steps:**
  1. Open Menu (☰) -> Tap "ℹ Info".
  2. Info dialog displays: IP address, Wi-Fi SSID/Strength, Capture Resolution/FPS, HDMI Signal presence, USB Free Storage, CPU Temperature, and Uptime.
  3. Press "Close" to dismiss.
* **Status:** ✅ Fully Supported

### 12. Power Management (Shutdown)
* **User Story:** As a user, I want to safely shut down the Raspberry Pi before cutting power.
* **Steps:**
  1. Open Menu (☰) -> Tap "⏻ Power".
  2. Power confirmation dialog appears.
  3. Press "Shut down".
  4. App gracefully stops any active recording.
  5. Device powers off via `systemctl poweroff`.
* **Status:** ✅ Fully Supported
