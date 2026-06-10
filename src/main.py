#!/usr/bin/env python3
"""
DVR entry point.
GStreamer preview renders directly into a tk.Frame X11 window (via XID) —
the same GPU-overlay pattern as picamera.start_preview(), adapted for
the TC358743 V4L2 capture device.
"""
import os
import sys

os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("GST_PLUGIN_PATH",
                      "/usr/lib/arm-linux-gnueabihf/gstreamer-1.0")

# DVR_UI_PREVIEW=1 runs the whole UI on a dev box with no GStreamer/hardware —
# for iterating on layout. Real hardware path imports Gst; the stub path skips it.
PREVIEW = os.environ.get("DVR_UI_PREVIEW") == "1"

import tkinter as tk

sys.path.insert(0, os.path.dirname(__file__))

from app import DVRApp


def main():
    if PREVIEW:
        print("DVR: starting in PREVIEW mode (hardware stubs)")
        from stubs import FakePipeline as Pipeline, \
                          FakeStorage as StorageManager, \
                          FakeWifi as WifiManager
    else:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        from pipeline import Pipeline
        from storage  import StorageManager
        from wifi     import WifiManager

    root = tk.Tk()
    if not PREVIEW:
        # Hide cursor on the touchscreen (keep it on a dev box)
        root.config(cursor='none')

    storage  = StorageManager()
    storage.start()

    wifi     = WifiManager()
    pipeline = Pipeline()

    DVRApp(root, pipeline, storage, wifi)

    try:
        root.mainloop()
    finally:
        pipeline.stop()
        storage.stop()


if __name__ == "__main__":
    main()
