"""
USB storage manager.
Detects USB drives, mounts them, reports free space, and handles safe eject.
"""
import os
import subprocess
import threading
import time


class StorageManager:
    def __init__(self):
        self._drives = {}   # {device_path: mount_point}
        self._lock   = threading.Lock()
        self._monitor_thread = None
        self._running = False

        # Callbacks
        self.on_drive_added   = None  # (device, mount_point)
        self.on_drive_removed = None  # (device)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor, daemon=True)
        self._monitor_thread.start()

    def stop(self):
        self._running = False

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def drives(self) -> dict:
        with self._lock:
            return dict(self._drives)

    @property
    def primary_mount(self) -> str | None:
        """Return the first mounted USB drive path, or None."""
        with self._lock:
            if self._drives:
                return next(iter(self._drives.values()))
        return None

    def free_bytes(self, mount_point: str) -> int:
        try:
            s = os.statvfs(mount_point)
            return s.f_bavail * s.f_frsize
        except OSError:
            return 0

    def total_bytes(self, mount_point: str) -> int:
        try:
            s = os.statvfs(mount_point)
            return s.f_blocks * s.f_frsize
        except OSError:
            return 0

    def free_gb(self, mount_point: str) -> float:
        return self.free_bytes(mount_point) / 1e9

    def eject(self, device: str) -> bool:
        """Safely unmount and power off the drive. Returns True on success."""
        mount = self._drives.get(device)
        if mount:
            try:
                subprocess.run(["sync"], check=True, timeout=10)
                subprocess.run(
                    ["udisksctl", "unmount", "--block-device", device],
                    check=True, timeout=15
                )
                subprocess.run(
                    ["udisksctl", "power-off", "--block-device", device],
                    check=True, timeout=10
                )
                with self._lock:
                    self._drives.pop(device, None)
                if self.on_drive_removed:
                    self.on_drive_removed(device)
                return True
            except subprocess.CalledProcessError:
                return False
        return False

    def format_usb(self, device: str, label: str = "DVR") -> bool:
        """
        Quick-format the first partition of device as exFAT.
        DESTRUCTIVE — only called after explicit user confirmation.
        """
        partition = device + "1"
        try:
            subprocess.run(["umount", partition], timeout=5)
        except Exception:
            pass
        try:
            result = subprocess.run(
                ["mkfs.exfat", "-n", label, partition],
                capture_output=True, text=True, timeout=60
            )
            return result.returncode == 0
        except Exception:
            return False

    # ── Monitor thread ────────────────────────────────────────────────────────

    def _monitor(self):
        known = set()
        while self._running:
            current = self._detect_usb_devices()
            added   = current - known
            removed = known - current
            for dev in added:
                mp = self._mount(dev)
                if mp:
                    with self._lock:
                        self._drives[dev] = mp
                    if self.on_drive_added:
                        self.on_drive_added(dev, mp)
            for dev in removed:
                with self._lock:
                    self._drives.pop(dev, None)
                if self.on_drive_removed:
                    self.on_drive_removed(dev)
            known = current
            time.sleep(2)

    def _detect_usb_devices(self) -> set:
        """Return set of USB block device paths (e.g. /dev/sda1)."""
        devices = set()
        try:
            out = subprocess.check_output(
                ["lsblk", "-o", "NAME,TRAN,TYPE", "--json"],
                text=True, timeout=3
            )
            import json
            data = json.loads(out)
            for dev in data.get("blockdevices", []):
                if dev.get("tran") == "usb":
                    for child in dev.get("children", []):
                        if child.get("type") == "part":
                            devices.add(f"/dev/{child['name']}")
                    if not dev.get("children") and dev.get("type") == "disk":
                        devices.add(f"/dev/{dev['name']}")
        except Exception:
            pass
        return devices

    def _mount(self, device: str) -> str | None:
        """
        Mount via udisksctl (polkit-permitted for user 'pi', no root needed).
        udisks mounts under /run/media/pi/<label>. Returns the mount point.
        """
        # Already mounted?
        try:
            for line in open("/proc/mounts"):
                if line.startswith(device + " "):
                    return line.split()[1]
        except Exception:
            pass

        try:
            r = subprocess.run(
                ["udisksctl", "mount", "--no-user-interaction",
                 "--block-device", device],
                capture_output=True, text=True, timeout=15
            )
            # Output: "Mounted /dev/sda1 at /run/media/pi/LABEL."
            out = (r.stdout + r.stderr).strip()
            if " at " in out:
                return out.split(" at ", 1)[1].rstrip(". \n")
            # Already-mounted message also lands here — re-read /proc/mounts
            for line in open("/proc/mounts"):
                if line.startswith(device + " "):
                    return line.split()[1]
        except Exception:
            pass
        return None
