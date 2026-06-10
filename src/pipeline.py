"""
GStreamer pipeline — ONE pipeline, no subprocesses.

A V4L2 capture node (TC358743) and the I2S ALSA device can each only be
opened once for streaming, so preview and recording must share a single
pipeline via tee elements:

    v4l2src ─→ vtee ─┬─ queue ─→ xvimagesink                (preview, always)
                     └─ [record video branch, added on demand]
    alsasrc ─→ atee ─┬─ queue ─→ level ─→ fakesink          (VU meter, always)
                     └─ [record audio branch, added on demand]

The record branch is a single Gst.Bin (encoder + muxer + filesink) that is
dynamically added to the running pipeline when recording starts and removed
— after a clean EOS so the MP4 moov atom is written — when it stops.

The preview sink renders straight into the Tkinter frame's X11 window
(GstVideoOverlay), the same GPU-overlay idea as picamera.start_preview().
"""
import os
import time
import threading
from datetime import datetime

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import Gst, GstVideo, GLib

# ── Config (env-overridable so 2B↔3B needs no code change) ───────────────────
# IMPORTANT: capture width/height must MATCH the timing the TC358743 receives
# from the HDMI source. The chip captures whatever the upscaler sends — so to
# test at 720p, set your CVBS→HDMI upscaler to output 720p (and advertise a
# 720p EDID). For a 1080p source you must capture 1080p.
#   2B test:  export DVR_WIDTH=1280 DVR_HEIGHT=720
#   3B/1080p: leave defaults (or export DVR_WIDTH=1920 DVR_HEIGHT=1080)
VIDEO_DEVICE = os.environ.get("DVR_VIDEO_DEV", "/dev/video0")
AUDIO_DEVICE = os.environ.get("DVR_AUDIO_DEV", "default")   # see asound.conf
WIDTH        = int(os.environ.get("DVR_WIDTH",  "1920"))
HEIGHT       = int(os.environ.get("DVR_HEIGHT", "1080"))
FRAMERATE    = os.environ.get("DVR_FPS", "25/1")            # PAL/Hi8=25, NTSC=30/1
PIXEL_FORMAT = "UYVY"                                       # TC358743 native output
BITRATE      = int(os.environ.get("DVR_BITRATE", "10000000"))  # 10 Mbit/s
CLIP_SECONDS = int(os.environ.get("DVR_CLIP_SECONDS", str(30 * 60)))
EOS_TIMEOUT  = 6.0               # seconds to wait for a clip to finalize


class Pipeline:
    def __init__(self):
        self._pipeline   = None
        self._vtee       = None
        self._atee       = None
        self._preview    = None
        self._xid        = None

        self._recording  = False
        self._rec_start  = 0.0
        self._clip_index = 0
        self._output_dir = None
        self._split_timer = None

        self._rec_bin    = None
        self._rec_vpad   = None      # vtee request pad feeding the record bin
        self._rec_apad   = None      # atee request pad feeding the record bin
        self._eos_done   = threading.Event()
        self._lock       = threading.RLock()

        # Live-tunable capture parameters (seeded from env, changeable at runtime)
        self.width   = WIDTH
        self.height  = HEIGHT
        self.fps     = FRAMERATE
        self.bitrate = BITRATE

        # Callbacks (attached by the UI)
        self.on_signal_change = None  # (bool has_signal)
        self.on_level         = None  # (peak_l, peak_r, rms_l, rms_r) dBFS
        self.on_error         = None  # (str message)
        self.on_clip_started  = None  # (str filepath)
        self.on_still_saved   = None  # (str filepath)

        self._build()

    # ── Build the always-on pipeline ──────────────────────────────────────────

    def _build(self):
        desc = (
            f"v4l2src device={VIDEO_DEVICE} name=vsrc ! "
            f"video/x-raw,format={PIXEL_FORMAT},width={self.width},height={self.height},"
            f"framerate={self.fps} ! "
            "tee name=vtee allow-not-linked=true "
            # Preview: let Xv handle UYVY + scaling on the GPU (zero CPU convert).
            # If the preview is black, your Xv adaptor lacks UYVY — insert
            #   v4l2convert ! video/x-raw,format=I420,width=800,height=480
            # before xvimagesink.
            "vtee. ! queue leaky=downstream max-size-buffers=2 ! "
            "xvimagesink name=preview sync=false "

            f"alsasrc device={AUDIO_DEVICE} name=asrc ! "
            "audio/x-raw,rate=48000,channels=2 ! "
            "tee name=atee allow-not-linked=true "
            "atee. ! queue leaky=downstream max-size-buffers=2 ! "
            # 50 ms updates; peak-hold ballistics (1.5 s hold, 12 dB/s falloff)
            # so 'decay' is PPM-like. The UI also applies its own ballistics.
            "level name=alevel interval=50000000 post-messages=true "
            "peak-ttl=1500000000 peak-falloff=12 ! "
            "fakesink sync=false "
        )
        self._pipeline = Gst.parse_launch(desc)
        self._vtee     = self._pipeline.get_by_name("vtee")
        self._atee     = self._pipeline.get_by_name("atee")
        self._preview  = self._pipeline.get_by_name("preview")

        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error",   self._on_error)
        bus.connect("message::warning", lambda *_: None)
        bus.connect("message::element", self._on_element)

    # ── Preview window ────────────────────────────────────────────────────────

    def set_xid(self, xid):
        self._xid = xid
        if self._preview:
            self._preview.set_window_handle(xid)

    def play(self):
        if self._xid and self._preview:
            self._preview.set_window_handle(self._xid)
        self._pipeline.set_state(Gst.State.PLAYING)

    def stop(self):
        if self._recording:
            self.stop_recording()
        self._pipeline.set_state(Gst.State.NULL)

    def reconfigure(self, width, height, fps=None) -> bool:
        """
        Change capture resolution live by tearing down and rebuilding the
        pipeline. Refused while recording. The capture size must match the
        timing the HDMI source actually sends, or there will be no preview.
        """
        with self._lock:
            if self._recording:
                return False
            self.width  = int(width)
            self.height = int(height)
            if fps:
                self.fps = fps
            try:
                self._pipeline.set_state(Gst.State.NULL)
            except Exception:
                pass
            self._build()      # recreates pipeline/tees/preview/bus
            self.play()        # reattaches the preview window handle
            return True

    # ── Recording ─────────────────────────────────────────────────────────────

    def start_recording(self, output_dir: str):
        with self._lock:
            if self._recording:
                return
            self._output_dir = output_dir
            self._clip_index = 0
            try:
                self._start_clip()
                self._recording = True
                self._rec_start = time.monotonic()
            except Exception as e:
                self._recording = False
                if self.on_error:
                    self.on_error(f"Failed to start recording: {e}")

    def stop_recording(self):
        with self._lock:
            if not self._recording:
                return
            self._recording = False
        if self._split_timer:
            self._split_timer.cancel()
            self._split_timer = None
        # Finalize off the UI thread — EOS flush can take up to EOS_TIMEOUT.
        threading.Thread(target=self._run_finalize, args=(False,),
                         daemon=True).start()

    def _auto_split(self):
        # Runs on the timer thread — safe to block on EOS here.
        if not self._recording:
            return
        self._run_finalize(True)

    def _run_finalize(self, start_new: bool):
        with self._lock:
            self._finalize_clip()
            if start_new and self._recording:
                self._clip_index += 1
                try:
                    self._start_clip()
                except Exception as e:
                    self._recording = False
                    if self.on_error:
                        self.on_error(f"Failed to split clip: {e}")

    # ── Add the record branch ─────────────────────────────────────────────────

    def _start_clip(self):
        name = (datetime.now().strftime("clip_%Y%m%d_%H%M%S")
                + f"_{self._clip_index:03d}.mp4")
        path = os.path.join(self._output_dir, name)

        # v4l2convert (bcm2835 ISP) does UYVY→I420 in hardware; if unavailable
        # on your kernel, swap it for the CPU element 'videoconvert'.
        desc = (
            "queue name=vq max-size-buffers=8 ! "
            "v4l2convert ! video/x-raw,format=I420 ! "
            "v4l2h264enc name=venc extra-controls=\"controls,"
            f"video_bitrate={self.bitrate},h264_i_frame_period=30\" ! "
            "h264parse config-interval=-1 ! mux. "

            "queue name=aq max-size-buffers=16 ! "
            "audioconvert ! audioresample ! "
            "voaacenc bitrate=192000 ! aacparse ! mux. "

            f"mp4mux name=mux ! filesink name=fsink async=false location=\"{path}\" "
        )
        try:
            bin_ = Gst.parse_bin_from_description(desc, False)
        except Exception as e:
            raise RuntimeError(f"GStreamer parse error: {e}")

        bin_._eos_v = False
        bin_._eos_a = False

        # Expose the two queue sink pads as named ghost pads.
        for qname, gname in (("vq", "v"), ("aq", "a")):
            q = bin_.get_by_name(qname)
            if not q:
                raise RuntimeError(f"Could not find queue {qname} in record bin")
            bin_.add_pad(Gst.GhostPad.new(gname, q.get_static_pad("sink")))

        # Detect EOS reaching the filesink → clip fully flushed.
        fsink = bin_.get_by_name("fsink")
        if not fsink:
            raise RuntimeError("Could not find filesink in record bin")
        fsink.get_static_pad("sink").add_probe(
            Gst.PadProbeType.EVENT_DOWNSTREAM, self._on_filesink_event)

        self._pipeline.add(bin_)

        self._rec_vpad = self._vtee.get_request_pad("src_%u")
        self._rec_apad = self._atee.get_request_pad("src_%u")
        if not self._rec_vpad or not self._rec_apad:
            self._pipeline.remove(bin_)
            raise RuntimeError("Could not request tee pads")

        self._rec_vpad.link(bin_.get_static_pad("v"))
        self._rec_apad.link(bin_.get_static_pad("a"))

        if bin_.sync_state_with_parent() == Gst.StateChangeReturn.FAILURE:
            self._vtee.release_request_pad(self._rec_vpad)
            self._atee.release_request_pad(self._rec_apad)
            self._pipeline.remove(bin_)
            raise RuntimeError("Could not sync record bin state")

        self._rec_bin = bin_
        self._eos_done.clear()

        self._split_timer = threading.Timer(CLIP_SECONDS, self._auto_split)
        self._split_timer.daemon = True
        self._split_timer.start()

        if self.on_clip_started:
            self.on_clip_started(path)

    # ── Still frame grab ──────────────────────────────────────────────────────

    def grab_still(self, path: str) -> bool:
        """
        Capture one preview frame to a JPEG, independent of recording.

        Adds a transient branch off the video tee (software videoconvert so it
        never contends with the encoder's ISP context during recording),
        encodes a single frame, then tears the branch down. A lone JPEG buffer
        is a complete file, so no EOS dance is needed — we just stop after the
        first frame and drop the rest.
        """
        with self._lock:
            if self._pipeline is None or self._vtee is None:
                return False
            try:
                desc = (
                    "queue name=gq leaky=downstream max-size-buffers=1 ! "
                    "videoconvert ! video/x-raw,format=I420 ! "
                    "jpegenc quality=85 ! "
                    f"filesink name=gfsink async=false location=\"{path}\""
                )
                bin_ = Gst.parse_bin_from_description(desc, False)
                q = bin_.get_by_name("gq")
                bin_.add_pad(Gst.GhostPad.new("sink", q.get_static_pad("sink")))
                self._pipeline.add(bin_)
                gpad = self._vtee.get_request_pad("src_%u")
                gpad.link(bin_.get_static_pad("sink"))
                bin_.sync_state_with_parent()
            except Exception as e:
                if self.on_error:
                    self.on_error(f"grab: {e}")
                return False

        done = {"v": False}
        fsink = bin_.get_by_name("gfsink")

        def _teardown():
            # Block the tee feed, unlink and dispose of the branch.
            gpad.add_probe(Gst.PadProbeType.BLOCK_DOWNSTREAM,
                           lambda p, i: Gst.PadProbeReturn.OK)
            try:
                gpad.unlink(bin_.get_static_pad("sink"))
            except Exception:
                pass
            bin_.set_state(Gst.State.NULL)
            try:
                self._vtee.release_request_pad(gpad)
            except Exception:
                pass
            try:
                self._pipeline.remove(bin_)
            except Exception:
                pass
            if self.on_still_saved:
                self.on_still_saved(path)
            return False   # GLib.idle_add: run once

        def _on_buf(pad, info):
            if done["v"]:
                return Gst.PadProbeReturn.DROP   # only the first frame
            done["v"] = True
            GLib.idle_add(_teardown)
            return Gst.PadProbeReturn.OK         # let this one through to disk

        fsink.get_static_pad("sink").add_probe(Gst.PadProbeType.BUFFER, _on_buf)
        return True

    # ── Remove the record branch with a clean EOS ─────────────────────────────

    def _finalize_clip(self):
        bin_ = self._rec_bin
        if bin_ is None:
            return
        self._eos_done.clear()

        # Block each tee feed, then inject EOS into that branch from the probe.
        self._rec_vpad.add_probe(Gst.PadProbeType.BLOCK_DOWNSTREAM,
                                 self._block_eos, (bin_, "v"))
        self._rec_apad.add_probe(Gst.PadProbeType.BLOCK_DOWNSTREAM,
                                 self._block_eos, (bin_, "a"))

        if not self._eos_done.wait(EOS_TIMEOUT):
            print("[pipeline] EOS timeout — clip may be truncated")

        bin_.set_state(Gst.State.NULL)
        self._vtee.release_request_pad(self._rec_vpad)
        self._atee.release_request_pad(self._rec_apad)
        self._pipeline.remove(bin_)
        self._rec_bin = self._rec_vpad = self._rec_apad = None

    def _block_eos(self, pad, info, data):
        bin_, which = data
        sent_attr = "_eos_" + which
        if not getattr(bin_, sent_attr):
            setattr(bin_, sent_attr, True)
            bin_.get_static_pad(which).send_event(Gst.Event.new_eos())
        return Gst.PadProbeReturn.OK   # stay blocked; no more buffers

    def _on_filesink_event(self, pad, info):
        ev = info.get_event()
        if ev and ev.type == Gst.EventType.EOS:
            self._eos_done.set()
        return Gst.PadProbeReturn.OK

    # ── State queries ─────────────────────────────────────────────────────────

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def rec_elapsed(self) -> float:
        return time.monotonic() - self._rec_start if self._recording else 0.0

    def query_signal(self) -> bool:
        """True if the TC358743 reports valid input timings."""
        try:
            import subprocess
            r = subprocess.run(
                ["v4l2-ctl", f"--device={VIDEO_DEVICE}", "--query-dv-timings"],
                capture_output=True, text=True, timeout=1)
            return "width" in r.stdout.lower()
        except Exception:
            return False

    # ── Bus handlers ──────────────────────────────────────────────────────────

    def _on_error(self, bus, msg):
        err, _ = msg.parse_error()
        if self.on_error:
            self.on_error(str(err))

    def _on_element(self, bus, msg):
        s = msg.get_structure()
        if s and s.get_name() == "level" and self.on_level:
            peak = s.get_value("peak")
            rms  = s.get_value("rms")
            if peak and rms and len(peak) >= 2 and len(rms) >= 2:
                # Per-channel instantaneous peak + RMS, both in dBFS. The UI
                # turns these into PPM/VU ballistics and a clip indicator.
                self.on_level(float(peak[0]), float(peak[1]),
                              float(rms[0]),  float(rms[1]))
