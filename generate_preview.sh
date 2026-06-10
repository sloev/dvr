#!/bin/bash
set -e

# Resolution of the DVR screen
RES="800x480x24"
OUT_DIR="previews"
mkdir -p "$OUT_DIR"

# Ensure dependencies are installed (for local use; CI will handle this)
if ! command -v xdotool &> /dev/null; then
    echo "==> Installing xdotool..."
    sudo apt-get update && sudo apt-get install -y xdotool
fi

echo "==> Starting DVR UI in preview mode (virtual frame buffer)..."
export DVR_UI_PREVIEW=1
export DISPLAY=:99

# Start xvfb in the background
Xvfb :99 -screen 0 $RES -ac +extension GLX +render -noreset &
XVFB_PID=$!

# Give Xvfb a moment to start
sleep 2

# Start the app and capture logs (unbuffered)
python3 -u src/main.py > "$OUT_DIR/app.log" 2>&1 &
APP_PID=$!

echo "==> Waiting for UI to render (Idle)..."
# Wait for the splash screen to pass (SPLASH_HOLD_MS = 2500)
# and for the app to settle. We wait 10s to be absolutely sure.
sleep 10
scrot "$OUT_DIR/preview_idle.png"

echo "==> Toggling Recording..."
# REC button is at approx (722, 436)
# x=722, y=436 (BOT_H=88, H=480, so bottom row starts at 392. 392 + 44 = 436)
xdotool mousemove 722 436 click 1

sleep 3
scrot "$OUT_DIR/preview_recording.png"

echo "==> Toggling Menu..."
# Menu button (☰) is at approx (51, 436)
# 8 + 86/2 = 51
xdotool mousemove 51 436 click 1

sleep 2
scrot "$OUT_DIR/preview_menu.png"

echo "==> Application Logs:"
cat "$OUT_DIR/app.log"

echo "==> Cleaning up..."
kill $APP_PID || true
kill $XVFB_PID || true

echo "==> Previews saved to $OUT_DIR/"
ls -1 "$OUT_DIR/"
