#!/bin/bash
# dvr-wifi-save.sh — root helper invoked by the app (via sudo) after a
# successful Wi-Fi connect. Mirrors NM keyfiles onto the FAT partition so the
# saved-network list persists across the read-only/tmpfs root.
set -e

SRC=/etc/NetworkManager/system-connections
DST=/boot/firmware/dvr-wifi

[ -d "$(dirname "$DST")" ] || exit 0
mkdir -p "$DST"
shopt -s nullglob

declare -A live
for f in "$SRC"/*.nmconnection; do
    bn=$(basename "$f"); live[$bn]=1
    cp -f "$f" "$DST/$bn"
done
# Prune networks that were forgotten.
for f in "$DST"/*.nmconnection; do
    bn=$(basename "$f"); [ -n "${live[$bn]:-}" ] || rm -f "$f"
done
sync
