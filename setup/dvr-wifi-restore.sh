#!/bin/bash
# dvr-wifi-restore.sh — runs every boot before NetworkManager.
# Copies saved Wi-Fi keyfiles from the writable FAT partition into the
# (tmpfs-overlaid, read-only-root) NM directory with the perms NM requires.
# This is how the "growing list of hotspots" survives a read-only root.
set -e

SRC=/boot/firmware/dvr-wifi
DST=/etc/NetworkManager/system-connections

mkdir -p "$DST"
[ -d "$SRC" ] || exit 0

shopt -s nullglob
for f in "$SRC"/*.nmconnection; do
    install -m 600 -o root -g root "$f" "$DST/"
done
