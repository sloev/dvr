"""
WiFi manager wrapping nmcli.

On the read-only appliance, NetworkManager's connection dir lives on the
tmpfs overlay and is wiped on reboot. To make the hotspot list persist, every
successful connect is mirrored as a keyfile onto the writable FAT partition
(/boot/firmware/dvr-wifi); dvr-wifi-restore.service copies them back, with the
perms NM requires, on the next boot.
"""
import subprocess
import threading
import time


class WifiManager:
    def __init__(self):
        self._lock     = threading.Lock()
        self._networks = []   # list of dicts from last scan
        self._scanning = False

    # ── Status ────────────────────────────────────────────────────────────────

    def current_connection(self) -> dict | None:
        """Return {'ssid': ..., 'strength': ..., 'ip': ...} or None."""
        try:
            out = subprocess.check_output(
                ["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,IP4.ADDRESS",
                 "device", "wifi"],
                text=True, timeout=5
            )
            for line in out.splitlines():
                if line.startswith("yes:"):
                    parts = line.split(":")
                    return {
                        "ssid":     parts[1] if len(parts) > 1 else "",
                        "strength": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0,
                        "ip":       parts[3] if len(parts) > 3 else "",
                    }
        except Exception:
            pass
        return None

    def is_connected(self) -> bool:
        return self.current_connection() is not None

    # ── Scan ──────────────────────────────────────────────────────────────────

    def scan(self, callback=None):
        """Non-blocking scan. Calls callback(list_of_networks) when done."""
        def _do_scan():
            self._scanning = True
            nets = self._scan_sync()
            with self._lock:
                self._networks = nets
            self._scanning = False
            if callback:
                callback(nets)

        t = threading.Thread(target=_do_scan, daemon=True)
        t.start()

    def _scan_sync(self) -> list:
        try:
            subprocess.run(
                ["nmcli", "device", "wifi", "rescan"],
                capture_output=True, timeout=8
            )
            time.sleep(2)
            out = subprocess.check_output(
                ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE",
                 "device", "wifi", "list"],
                text=True, timeout=5
            )
            nets = []
            seen = set()
            for line in out.splitlines():
                parts = line.split(":")
                if len(parts) < 4:
                    continue
                ssid     = parts[0].strip()
                strength = int(parts[1]) if parts[1].isdigit() else 0
                secure   = bool(parts[2].strip())
                in_use   = parts[3].strip() == "*"
                if ssid and ssid not in seen:
                    nets.append({
                        "ssid":     ssid,
                        "strength": strength,
                        "secure":   secure,
                        "in_use":   in_use,
                    })
                    seen.add(ssid)
            return sorted(nets, key=lambda n: -n["strength"])
        except Exception:
            return []

    @property
    def last_networks(self) -> list:
        with self._lock:
            return list(self._networks)

    # ── Connect / disconnect ──────────────────────────────────────────────────

    def connect(self, ssid: str, password: str = "") -> bool:
        """Connect to a network. Returns True on success."""
        try:
            cmd = ["nmcli", "device", "wifi", "connect", ssid]
            if password:
                cmd += ["password", password]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            ok = result.returncode == 0
            if ok:
                self.persist()
            return ok
        except Exception:
            return False

    def connect_known(self, ssid: str) -> bool:
        """Re-connect to a previously saved network."""
        try:
            result = subprocess.run(
                ["nmcli", "connection", "up", "id", ssid],
                capture_output=True, text=True, timeout=20
            )
            return result.returncode == 0
        except Exception:
            return False

    def disconnect(self) -> bool:
        try:
            result = subprocess.run(
                ["nmcli", "device", "disconnect", "wlan0"],
                capture_output=True, timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False

    def forget(self, ssid: str) -> bool:
        try:
            result = subprocess.run(
                ["nmcli", "connection", "delete", "id", ssid],
                capture_output=True, timeout=10
            )
            self.persist()   # re-sync the FAT copy so the deletion sticks
            return result.returncode == 0
        except Exception:
            return False

    # ── Persistence (read-only root) ──────────────────────────────────────────

    def persist(self):
        """
        Mirror NetworkManager's keyfiles onto the writable FAT partition so
        saved networks survive the read-only/tmpfs root.

        NM keyfiles and /boot/firmware are both root-only, so this is done via
        the narrow sudo helper dvr-wifi-save (installed + whitelisted in
        sudoers by the image build). No-op / harmless on a dev box.
        """
        try:
            subprocess.run(["sudo", "-n", "/usr/local/bin/dvr-wifi-save"],
                           capture_output=True, timeout=10)
        except Exception:
            pass

    # ── Known networks ────────────────────────────────────────────────────────

    def known_networks(self) -> list:
        """Return list of saved network SSIDs."""
        try:
            out = subprocess.check_output(
                ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
                text=True, timeout=5
            )
            return [
                line.split(":")[0]
                for line in out.splitlines()
                if ":802-11-wireless" in line
            ]
        except Exception:
            return []
