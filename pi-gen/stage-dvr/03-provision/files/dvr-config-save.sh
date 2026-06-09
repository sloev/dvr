#!/bin/bash
# dvr-config-save.sh — root helper invoked by the app (via sudo) to persist a
# capture setting into /boot/firmware/dvr.env (sourced by .xinitrc at boot).
# Strictly validates key and value so the sudo grant stays safe.
set -e

KEY="$1"
VAL="$2"

case "$KEY" in
    DVR_WIDTH|DVR_HEIGHT|DVR_FPS|DVR_BITRATE|DVR_CLIP_SECONDS) ;;
    *) echo "dvr-config-save: invalid key" >&2; exit 1 ;;
esac
# digits, optionally one slash (for fps like 25/1)
case "$VAL" in
    ''|*[!0-9/]*) echo "dvr-config-save: invalid value" >&2; exit 1 ;;
esac

ENVF=/boot/firmware/dvr.env
touch "$ENVF"
grep -v -E "^#?${KEY}=" "$ENVF" > "${ENVF}.tmp" 2>/dev/null || true
mv "${ENVF}.tmp" "$ENVF"
echo "${KEY}=${VAL}" >> "$ENVF"
sync
