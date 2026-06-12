#!/bin/bash
set -e

# Resolution of the DVR screen
RES="800x480x24"
OUT_DIR="previews"
mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR"/*.png


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

echo "==> Opening Playback Panel..."
xdotool mousemove 519 436 click 1
sleep 2
scrot "$OUT_DIR/preview_playback.png"

echo "==> Closing Playback Panel..."
xdotool mousemove 770 70 click 1
sleep 2

echo "==> Toggling Recording..."
xdotool mousemove 722 436 click 1
sleep 3
scrot "$OUT_DIR/preview_recording.png"

echo "==> Stopping Recording..."
xdotool mousemove 722 436 click 1
sleep 2

echo "==> Opening Menu..."
xdotool mousemove 51 436 click 1
sleep 2
scrot "$OUT_DIR/preview_menu.png"

echo "==> Opening Wi-Fi Panel..."
xdotool mousemove 200 150 click 1
sleep 2
scrot "$OUT_DIR/preview_wifi.png"

echo "==> Closing Wi-Fi Panel..."
xdotool mousemove 270 70 click 1
sleep 2

echo "==> Opening Menu for Stopmotion..."
xdotool mousemove 51 436 click 1
sleep 2

echo "==> Activating Stopmotion Mode..."
xdotool mousemove 600 150 click 1
sleep 2
scrot "$OUT_DIR/preview_stopmotion.png"

echo "==> Capturing Frame 1..."
xdotool mousemove 722 436 click 1
sleep 2

echo "==> Capturing Frame 2..."
xdotool mousemove 722 436 click 1
sleep 2

echo "==> Enabling Onion Skinning..."
xdotool mousemove 433 436 click 1
sleep 2
scrot "$OUT_DIR/preview_stopmotion_onion.png"

echo "==> Toggling Loop Preview On..."
xdotool mousemove 519 436 click 1
sleep 2
scrot "$OUT_DIR/preview_stopmotion_loop.png"

echo "==> Toggling Loop Preview Off..."
xdotool mousemove 519 436 click 1
sleep 2

echo "==> Opening Stopmotion Compile Dialog..."
xdotool mousemove 347 436 click 1
sleep 2
scrot "$OUT_DIR/preview_stopmotion_compile.png"

echo "==> Closing Compile Dialog..."
xdotool mousemove 450 280 click 1
sleep 2

echo "==> Opening Menu for Settings..."
xdotool mousemove 51 436 click 1
sleep 2

echo "==> Opening Settings Dialog..."
xdotool mousemove 200 280 click 1
sleep 2
scrot "$OUT_DIR/preview_settings.png"

echo "==> Closing Settings Dialog..."
xdotool mousemove 400 440 click 1
sleep 2

echo "==> Application Logs:"
cat "$OUT_DIR/app.log"

echo "==> Cleaning up..."
kill $APP_PID || true
kill $XVFB_PID || true

echo "==> Previews saved to $OUT_DIR/"
ls -1 "$OUT_DIR/"
