#!/bin/bash
set -e

echo "Installing screenshot dependencies..."
sudo apt-get update && sudo apt-get install -y xvfb imagemagick libfontconfig1-dev libxcb-shape0-dev libxcb-xfixes0-dev libxkbcommon-dev

echo "Installing slint-viewer..."
# Cargo is cached in the workflow, so this is fast on subsequent runs
cargo install slint-viewer

mkdir -p public/screenshots

capture() {
    name=$1
    echo "Capturing $name..."
    xvfb-run -s "-screen 0 1920x1080x24" bash -c "
      slint-viewer dvr_app/ui/main.slint &
      PID=\$!
      sleep 3
      import -window root public/screenshots/${name}.png
      kill \$PID
    "
}

# 1. Main UI
capture "main_ui"

# 2. Stopmotion Mode
sed -i 's/is-stopmotion-mode: false/is-stopmotion-mode: true/' dvr_app/ui/main.slint
capture "stopmotion_mode"
sed -i 's/is-stopmotion-mode: true/is-stopmotion-mode: false/' dvr_app/ui/main.slint

# 3. Wi-Fi Mode
sed -i 's/is-wifi-mode: false/is-wifi-mode: true/' dvr_app/ui/main.slint
capture "wifi_mode"
sed -i 's/is-wifi-mode: true/is-wifi-mode: false/' dvr_app/ui/main.slint

# 4. Settings Mode
sed -i 's/is-settings-mode: false/is-settings-mode: true/' dvr_app/ui/main.slint
capture "settings_mode"
sed -i 's/is-settings-mode: true/is-settings-mode: false/' dvr_app/ui/main.slint

# 5. Gallery Mode
sed -i 's/is-gallery-mode: false/is-gallery-mode: true/' dvr_app/ui/main.slint
capture "gallery_mode"
sed -i 's/is-gallery-mode: true/is-gallery-mode: false/' dvr_app/ui/main.slint

# 6. Format USB Confirmation
sed -i 's/is-format-confirm-mode: false/is-format-confirm-mode: true/' dvr_app/ui/main.slint
capture "format_confirm_mode"
sed -i 's/is-format-confirm-mode: true/is-format-confirm-mode: false/' dvr_app/ui/main.slint

echo "Screenshots generated successfully."
