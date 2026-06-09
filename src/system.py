"""System helpers: shutdown, reboot, temperature, uptime."""
import os
import subprocess
import time


def shutdown():
    subprocess.run(["systemctl", "poweroff"], check=False)


def reboot():
    subprocess.run(["systemctl", "reboot"], check=False)


def cpu_temp() -> float:
    """Return CPU temperature in °C."""
    try:
        raw = open("/sys/class/thermal/thermal_zone0/temp").read().strip()
        return int(raw) / 1000.0
    except OSError:
        return 0.0


def uptime_seconds() -> float:
    try:
        return float(open("/proc/uptime").read().split()[0])
    except OSError:
        return 0.0


# Bookworm keeps the FAT firmware/boot partition here; it stays writable even
# when the root overlay is read-only.
BOOT_FW = "/boot/firmware"

# Settings persisted to /boot/firmware/dvr.env (sourced by .xinitrc at boot).
SETTINGS_KEYS = {"DVR_WIDTH", "DVR_HEIGHT", "DVR_FPS",
                 "DVR_BITRATE", "DVR_CLIP_SECONDS"}


def save_setting(key: str, value) -> bool:
    """
    Persist a capture setting across reboots. The settings file lives on the
    read-only-protected FAT partition, so the write goes through the whitelisted
    root helper dvr-config-save. Falls back to a user file on a dev box.
    Returns True if it was persisted somewhere.
    """
    if key not in SETTINGS_KEYS:
        return False
    try:
        r = subprocess.run(
            ["sudo", "-n", "/usr/local/bin/dvr-config-save", key, str(value)],
            capture_output=True, timeout=10)
        if r.returncode == 0:
            return True
    except Exception:
        pass
    # Dev fallback (no appliance helper present)
    try:
        d = os.path.expanduser("~/.config/dvr")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "dvr.env")
        lines = []
        if os.path.exists(path):
            lines = [ln for ln in open(path)
                     if not ln.strip().lstrip("#").startswith(key + "=")]
        lines.append(f"{key}={value}\n")
        open(path, "w").writelines(lines)
        return True
    except Exception:
        return False


def remount_boot_rw():
    """Temporarily remount the firmware partition read-write for config edits."""
    subprocess.run(["mount", "-o", "remount,rw", BOOT_FW], check=False)


def remount_boot_ro():
    subprocess.run(["mount", "-o", "remount,ro", BOOT_FW], check=False)


def list_clips(directory: str) -> list:
    """Return sorted list of .mp4 clip dicts in directory."""
    clips = []
    if not directory or not os.path.isdir(directory):
        return clips
    for name in sorted(os.listdir(directory)):
        if not name.lower().endswith(".mp4"):
            continue
        path = os.path.join(directory, name)
        try:
            stat  = os.stat(path)
            clips.append({
                "name":    name,
                "path":    path,
                "size_mb": stat.st_size / 1e6,
                "mtime":   stat.st_mtime,
            })
        except OSError:
            pass
    return clips


def format_duration(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def format_size(bytes_: int) -> str:
    if bytes_ >= 1e9:
        return f"{bytes_/1e9:.1f} GB"
    if bytes_ >= 1e6:
        return f"{bytes_/1e6:.0f} MB"
    return f"{bytes_/1e3:.0f} KB"
