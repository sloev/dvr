"""
Headless stubs for DVR_UI_PREVIEW=1.

Let the full Tkinter UI run on an ordinary dev machine (no GStreamer, no
TC358743, no USB) so layout and interaction can be iterated and screenshotted.
Each stub mimics just the surface the UI touches, with gently animated fake
data (signal, audio levels, a couple of clips, a Wi-Fi list).
"""
import math
import os
import tempfile
import threading
import time


class FakePipeline:
    def __init__(self):
        print("FakePipeline: init (preview mode)")
        self.width, self.height, self.fps = 1920, 1080, "25/1"
        self.bitrate = 10_000_000
        self._recording = False
        self._rec_start = 0.0
        self.on_signal_change = None
        self.on_level = None
        self.on_error = None
        self.on_clip_started = None
        self.on_still_saved = None
        self._run = True
        threading.Thread(target=self._levels, daemon=True).start()

    # preview/window
    def set_xid(self, xid): pass
    def play(self): pass
    def stop(self): self._run = False

    def reconfigure(self, w, h, fps=None):
        if self._recording:
            return False
        self.width, self.height = int(w), int(h)
        if fps:
            self.fps = fps
        return True

    # recording
    @property
    def recording(self):
        return self._recording

    @property
    def rec_elapsed(self):
        return time.monotonic() - self._rec_start if self._recording else 0.0

    def start_recording(self, output_dir):
        self._recording = True
        self._rec_start = time.monotonic()

    def stop_recording(self):
        self._recording = False

    def query_signal(self):
        return True

    def grab_still(self, path):
        try:
            open(path, "wb").close()
        except OSError:
            pass
        if self.on_still_saved:
            self.on_still_saved(path)
        return True

    # animated fake meters: music-ish peaks with the odd transient
    def _levels(self):
        t = 0.0
        while self._run:
            if self.on_level:
                base = -18 + 10 * math.sin(t)
                spike = -2 if (int(t * 3) % 11 == 0) else 0
                pl = min(0.0, base + spike + 4 * math.sin(t * 7))
                pr = min(0.0, base + spike + 4 * math.sin(t * 6 + 1))
                self.on_level(pl, pr, pl - 6, pr - 6)
            t += 0.05
            time.sleep(0.05)


class FakeStorage:
    def __init__(self):
        self.on_drive_added = None
        self.on_drive_removed = None
        self._dir = tempfile.mkdtemp(prefix="dvr-preview-")
        # seed a couple of fake clips so the playback panel populates
        for n in ("clip_20240601_101500_000.mp4", "clip_20240601_120000_000.mp4"):
            try:
                with open(os.path.join(self._dir, n), "wb") as f:
                    f.write(b"\0" * 1024)
            except OSError:
                pass
        self._dev = "/dev/fake1"

    def start(self):
        if self.on_drive_added:
            threading.Timer(0.5, lambda: self.on_drive_added(self._dev, self._dir)).start()

    def stop(self): pass

    @property
    def drives(self):
        return {self._dev: self._dir}

    @property
    def primary_mount(self):
        return self._dir

    def free_gb(self, mp):
        return 12.3

    def eject(self, device):
        if self.on_drive_removed:
            self.on_drive_removed(device)
        return True

    def format_usb(self, device, label="DVR"):
        return True


class FakeWifi:
    def __init__(self):
        self._nets = [
            {"ssid": "Studio",    "strength": 88, "secure": True,  "in_use": True},
            {"ssid": "Tape Vault", "strength": 60, "secure": True,  "in_use": False},
            {"ssid": "GuestNet",  "strength": 35, "secure": False, "in_use": False},
        ]

    def current_connection(self):
        return {"ssid": "Studio", "strength": 88, "ip": "192.168.1.42"}

    def is_connected(self):
        return True

    def scan(self, callback=None):
        if callback:
            threading.Timer(0.6, lambda: callback(self._nets)).start()

    @property
    def last_networks(self):
        return list(self._nets)

    def connect(self, ssid, password=""):
        return True

    def connect_known(self, ssid):
        return True

    def disconnect(self):
        return True

    def forget(self, ssid):
        return True

    def known_networks(self):
        return ["Studio", "Tape Vault"]
