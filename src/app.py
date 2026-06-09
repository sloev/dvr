"""
DVR application — Tkinter + GStreamer.

Architecture mirrors picamera's GPU overlay pattern:
  GStreamer renders video directly into a tk.Frame's X11 window (via XID).
  Tkinter widgets sit on top as native X11 child windows — zero compositing.

Layout (800x480):
  ┌── top bar (48px) ────────────────────────────────────────────────────────┐
  │ [●sig] [input]            [HH:MM:SS:FF]             [°C] [●REC 00:00:00]│
  ├── video area (384px) ─────────────────────────────────────────────────────┤
  │  (GStreamer draws here — tap center to toggle chrome)                    │
  ├── bottom bar (48px) ──────────────────────────────────────────────────────┤
  │ [● REC]  [12.3GB]  [VU]       [⊕] [▶] [⏏] [WiFi] [⏻]                   │
  └───────────────────────────────────────────────────────────────────────────┘
Left panel  → WiFi (slides in from x=-280)
Right panel → Playback browser (slides in from x=800)
"""
import os
import sys
import time
import threading
import subprocess
from datetime import datetime

import tkinter as tk

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

import system
from storage import StorageManager
from wifi    import WifiManager

# ── Constants ─────────────────────────────────────────────────────────────────
W, H    = 800, 480
BAR_H   = 48
PANEL_W = 280
SLIDE_STEP = 28      # px per animation frame
SLIDE_MS   = 16      # ms between animation frames (~60fps panel slides)

C_BG     = '#0d0d0d'
C_PANEL  = '#181818'
C_PANEL2 = '#1e1e1e'
C_TEXT   = '#d8d8d8'
C_DIM    = '#555555'
C_RED    = '#e03030'
C_GREEN  = '#30c040'
C_AMBER  = '#e0a020'
C_BLUE   = '#3080e0'
C_BORDER = '#2a2a2a'

F_MONO   = ('DejaVu Sans Mono', 12)
F_MONO_L = ('DejaVu Sans Mono', 16)
F_UI     = ('DejaVu Sans', 13)
F_SMALL  = ('DejaVu Sans', 10)
F_BTN    = ('DejaVu Sans', 12)


def _btn(parent, text, cmd, w=None, **kw):
    b = tk.Button(
        parent, text=text, command=cmd,
        bg=C_PANEL2, fg=C_TEXT,
        activebackground=C_BORDER, activeforeground='white',
        relief='flat', bd=0, cursor='hand2',
        font=F_BTN, **kw
    )
    if w:
        b.config(width=w)
    return b


class DVRApp:
    def __init__(self, root, pipeline, storage: StorageManager, wifi: WifiManager):
        self.root     = root
        self.pipeline = pipeline
        self.storage  = storage
        self.wifi     = wifi

        self._chrome       = True
        self._wifi_open    = False
        self._play_open    = False
        self._clips        = []
        self._markers_path = None
        self._tap_x = self._tap_y = self._tap_t = 0

        root.title('')
        root.configure(bg='black')
        root.attributes('-fullscreen', True)
        root.wm_attributes('-type', 'splash')   # no WM decorations

        self._build()
        self._wire_pipeline()
        self._wire_storage()

        root.after(150, self._attach_preview)
        root.after(200, self._tick)
        root.after(3000, self._poll_signal)
        # GStreamer posts bus messages (VU level, errors) onto the GLib main
        # context. Tkinter runs its own loop, so we iterate GLib here to keep
        # those callbacks alive without a second thread.
        root.after(50, self._glib_pump)

    def _glib_pump(self):
        ctx = GLib.MainContext.default()
        n = 0
        while ctx.pending() and n < 10:
            ctx.iteration(False)
            n += 1
        self.root.after(50, self._glib_pump)

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self):
        # ── Video surface ── GStreamer paints into this frame's XID ──────────
        self.video_frame = tk.Frame(self.root, bg='black')
        self.video_frame.place(x=0, y=0, width=W, height=H)
        # Capture taps in the middle zone for chrome toggle
        self.video_frame.bind('<ButtonPress-1>',   self._on_tap_down)
        self.video_frame.bind('<ButtonRelease-1>',  self._on_tap_up)

        # ── Top bar ───────────────────────────────────────────────────────────
        self.top = tk.Frame(self.root, bg=C_PANEL, height=BAR_H)
        self.top.place(x=0, y=0, width=W, height=BAR_H)
        self.top.pack_propagate(False)

        self._sig_canvas = tk.Canvas(self.top, width=14, height=14,
                                     bg=C_PANEL, highlightthickness=0)
        self._sig_canvas.pack(side='left', padx=(10, 4), pady=17)
        self._sig_dot = self._sig_canvas.create_oval(1, 1, 13, 13,
                                                      fill=C_RED, outline='')

        self._input_lbl = tk.Label(self.top, text='NO SIGNAL',
                                    bg=C_PANEL, fg=C_DIM, font=F_SMALL)
        self._input_lbl.pack(side='left', padx=2)

        self._tc_lbl = tk.Label(self.top, text='00:00:00:00',
                                 bg=C_PANEL, fg=C_TEXT, font=F_MONO_L)
        self._tc_lbl.place(relx=0.5, rely=0.5, anchor='center')

        self._temp_lbl = tk.Label(self.top, text='--°C',
                                   bg=C_PANEL, fg=C_DIM, font=F_SMALL)
        self._temp_lbl.pack(side='right', padx=10)

        self._rec_lbl = tk.Label(self.top, text='',
                                  bg=C_PANEL, fg=C_RED, font=F_MONO)
        self._rec_lbl.pack(side='right', padx=6)

        # ── Bottom bar ────────────────────────────────────────────────────────
        self.bot = tk.Frame(self.root, bg=C_PANEL, height=BAR_H)
        self.bot.place(x=0, y=H - BAR_H, width=W, height=BAR_H)
        self.bot.pack_propagate(False)

        self._rec_btn = tk.Button(
            self.bot, text='● REC',
            font=('DejaVu Sans', 13, 'bold'),
            bg=C_PANEL, fg=C_RED,
            activebackground='#2a0808', activeforeground=C_RED,
            relief='solid', bd=1, cursor='hand2',
            command=self._toggle_record,
            padx=10
        )
        self._rec_btn.pack(side='left', padx=8, pady=6, ipady=3)

        self._space_lbl = tk.Label(self.bot, text='No USB',
                                    bg=C_PANEL, fg=C_DIM, font=F_SMALL)
        self._space_lbl.pack(side='left', padx=6)

        self._vu = tk.Canvas(self.bot, width=46, height=BAR_H - 10,
                              bg=C_PANEL, highlightthickness=0)
        self._vu.pack(side='left', padx=4, pady=5)
        # Two channel bars — updated by _draw_vu()
        self._vu_bars = [
            self._vu.create_rectangle(2,  2, 20, BAR_H-12, fill='#1a1a1a', outline=''),
            self._vu.create_rectangle(26, 2, 44, BAR_H-12, fill='#1a1a1a', outline=''),
        ]
        self._vu_levels = [-60.0, -60.0]

        for text, cmd in (
            ('⊕',    self._place_marker),
            ('▶',    self._toggle_playback),
            ('⏏',    self._eject_usb),
            ('WiFi', self._toggle_wifi),
            ('⚙',    self._settings_dialog),
            ('⏻',    self._power_dialog),
        ):
            b = _btn(self.bot, text, cmd)
            b.pack(side='right', padx=4, pady=6, ipady=3, ipadx=4)

        # ── WiFi panel (starts off left edge) ─────────────────────────────────
        self._wifi_x = -PANEL_W
        self.wifi_panel = tk.Frame(self.root, bg=C_PANEL)
        self.wifi_panel.place(x=self._wifi_x, y=BAR_H,
                               width=PANEL_W, height=H - 2 * BAR_H)
        self._build_wifi_panel()

        # ── Playback panel (starts off right edge) ────────────────────────────
        self._play_x = W
        self.play_panel = tk.Frame(self.root, bg=C_PANEL)
        self.play_panel.place(x=self._play_x, y=BAR_H,
                               width=PANEL_W, height=H - 2 * BAR_H)
        self._build_play_panel()

        self._lift_ui()

    def _lift_ui(self):
        for w in (self.top, self.bot, self.wifi_panel, self.play_panel):
            w.lift()

    # ── WiFi panel ────────────────────────────────────────────────────────────

    def _build_wifi_panel(self):
        f = self.wifi_panel

        hdr = tk.Frame(f, bg=C_PANEL)
        hdr.pack(fill='x', padx=8, pady=(8, 2))
        tk.Label(hdr, text='WiFi', bg=C_PANEL, fg=C_TEXT, font=F_UI).pack(side='left')
        _btn(hdr, '✕', self._toggle_wifi).pack(side='right')

        self._wifi_status = tk.Label(f, text='Not connected',
                                      bg=C_PANEL, fg=C_DIM, font=F_SMALL)
        self._wifi_status.pack(fill='x', padx=8, pady=2)

        self._wifi_lb = tk.Listbox(
            f, bg=C_PANEL2, fg=C_TEXT, selectbackground=C_BLUE,
            font=F_SMALL, relief='flat', bd=0,
            highlightthickness=1, highlightcolor=C_BORDER,
            activestyle='none', cursor='hand2'
        )
        self._wifi_lb.pack(fill='both', expand=True, padx=8, pady=4)
        self._wifi_lb.bind('<ButtonRelease-1>', self._on_wifi_select)

        pw_f = tk.Frame(f, bg=C_PANEL)
        pw_f.pack(fill='x', padx=8, pady=2)
        tk.Label(pw_f, text='PW:', bg=C_PANEL, fg=C_DIM,
                 font=F_SMALL).pack(side='left')
        self._pw_entry = tk.Entry(pw_f, show='*', bg=C_PANEL2, fg=C_TEXT,
                                   insertbackground=C_TEXT, relief='flat',
                                   font=('DejaVu Sans', 11))
        self._pw_entry.pack(side='left', fill='x', expand=True, ipady=4, padx=4)
        self._pw_entry.bind('<Return>', lambda _: self._connect_with_pw())

        row = tk.Frame(f, bg=C_PANEL)
        row.pack(fill='x', padx=8, pady=4)
        for t, c in (('↻ Scan', self._scan_wifi), ('Connect', self._connect_with_pw)):
            _btn(row, t, c).pack(side='left', fill='x', expand=True,
                                  padx=2, ipady=5)

        self._wifi_pending = None

    # ── Playback panel ────────────────────────────────────────────────────────

    def _build_play_panel(self):
        f = self.play_panel

        hdr = tk.Frame(f, bg=C_PANEL)
        hdr.pack(fill='x', padx=8, pady=(8, 2))
        tk.Label(hdr, text='Recordings', bg=C_PANEL,
                 fg=C_TEXT, font=F_UI).pack(side='left')
        _btn(hdr, '✕', self._toggle_playback).pack(side='right')

        self._clip_lb = tk.Listbox(
            f, bg=C_PANEL2, fg=C_TEXT, selectbackground=C_BLUE,
            font=F_SMALL, relief='flat', bd=0,
            highlightthickness=1, highlightcolor=C_BORDER,
            activestyle='none', cursor='hand2'
        )
        self._clip_lb.pack(fill='both', expand=True, padx=8, pady=4)
        self._clip_lb.bind('<Double-Button-1>', lambda _: self._play_clip())

        row = tk.Frame(f, bg=C_PANEL)
        row.pack(fill='x', padx=8, pady=4)
        for t, c in (
            ('▶ Play', self._play_clip),
            ('↻',      self._refresh_clips),
            ('✕ Del',  self._delete_clip),
        ):
            _btn(row, t, c).pack(side='left', fill='x', expand=True,
                                  padx=2, ipady=5)

    # ── Pipeline attachment ───────────────────────────────────────────────────

    def _attach_preview(self):
        """Hand the video frame's X11 window ID to GStreamer."""
        self.root.update_idletasks()          # ensure the frame is realized
        xid = self.video_frame.winfo_id()
        self.pipeline.set_xid(xid)
        self.pipeline.play()

    def _wire_pipeline(self):
        self.pipeline.on_level        = self._on_level
        self.pipeline.on_signal_change = self._on_signal_change
        self.pipeline.on_error        = lambda m: print(f'[gst] {m}', file=sys.stderr)

    def _wire_storage(self):
        self.storage.on_drive_added   = self._on_drive_added
        self.storage.on_drive_removed = self._on_drive_removed

    # ── Tick (200 ms) ─────────────────────────────────────────────────────────

    def _tick(self):
        now = datetime.now()
        ff  = now.microsecond // 40000   # 0-24 frame counter at 25fps
        self._tc_lbl.config(text=now.strftime('%H:%M:%S') + f':{ff:02d}')

        self._temp_lbl.config(text=f'{system.cpu_temp():.0f}°C')

        rec = self.pipeline.recording
        if rec:
            e = self.pipeline.rec_elapsed
            h, r = divmod(int(e), 3600)
            m, s = divmod(r, 60)
            self._rec_lbl.config(text=f'● {h:02d}:{m:02d}:{s:02d}')
        else:
            self._rec_lbl.config(text='')

        self._draw_vu()

        self.root.after(200, self._tick)

    def _poll_signal(self):
        has = self.pipeline.query_signal()
        self._on_signal_change(has)
        self.root.after(3000, self._poll_signal)

    # ── VU meter drawing ──────────────────────────────────────────────────────

    def _draw_vu(self):
        bar_h = BAR_H - 12
        xs = [(2, 20), (26, 44)]
        for i, db in enumerate(self._vu_levels):
            frac = (db + 60) / 60.0
            fill_h = max(1, int(frac * bar_h))
            x0, x1 = xs[i]
            col = C_GREEN if db < -6 else (C_AMBER if db < -2 else C_RED)
            self._vu.coords(self._vu_bars[i], x0, 2 + bar_h - fill_h, x1, 2 + bar_h)
            self._vu.itemconfig(self._vu_bars[i], fill=col)

    # ── Callbacks from pipeline / storage ────────────────────────────────────

    def _on_level(self, left: float, right: float):
        self._vu_levels = [left, right]

    def _on_signal_change(self, has: bool):
        if has:
            self._sig_canvas.itemconfig(self._sig_dot, fill=C_GREEN)
            self._input_lbl.config(text='1920×1080 25p', fg=C_GREEN)
        else:
            self._sig_canvas.itemconfig(self._sig_dot, fill=C_RED)
            self._input_lbl.config(text='NO SIGNAL', fg=C_DIM)

    def _on_drive_added(self, dev, mp):
        free = self.storage.free_gb(mp)
        col  = C_AMBER if free < 5 else C_TEXT
        self._space_lbl.config(text=f'{free:.1f} GB', fg=col)
        self._markers_path = os.path.join(mp, 'markers.txt')
        self._refresh_clips()

    def _on_drive_removed(self, dev):
        self._space_lbl.config(text='No USB', fg=C_DIM)
        self._markers_path = None
        if self.pipeline.recording:
            self.pipeline.stop_recording()

    # ── Recording ─────────────────────────────────────────────────────────────

    def _toggle_record(self):
        if self.pipeline.recording:
            self.pipeline.stop_recording()
            self._rec_btn.config(text='● REC', fg=C_RED,
                                  bg=C_PANEL, relief='solid')
        else:
            mp = self.storage.primary_mount
            if not mp:
                return
            self.pipeline.start_recording(mp)
            self._rec_btn.config(text='■ STOP', fg='white',
                                  bg=C_RED, relief='flat')

    def _place_marker(self):
        if not self.pipeline.recording or not self._markers_path:
            return
        ts = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        try:
            with open(self._markers_path, 'a') as f:
                f.write(f'{ts}  elapsed={self.pipeline.rec_elapsed:.1f}s\n')
        except OSError:
            pass

    # ── Eject ─────────────────────────────────────────────────────────────────

    def _eject_usb(self):
        if self.pipeline.recording:
            self.pipeline.stop_recording()
            time.sleep(0.5)
        for dev in list(self.storage.drives):
            ok = self.storage.eject(dev)
            if ok:
                self._space_lbl.config(text='Ejected', fg=C_GREEN)
                self.root.after(2000, lambda: self._space_lbl.config(
                    text='No USB', fg=C_DIM))

    # ── Playback ──────────────────────────────────────────────────────────────

    def _refresh_clips(self):
        mp = self.storage.primary_mount
        self._clips = system.list_clips(mp) if mp else []
        self._clip_lb.delete(0, 'end')
        for c in reversed(self._clips):
            size = system.format_size(int(c['size_mb'] * 1e6))
            self._clip_lb.insert('end', f"  {c['name']}  {size}")

    def _play_clip(self):
        idx = self._clip_lb.curselection()
        if not idx:
            return
        clips_rev = list(reversed(self._clips))
        clip = clips_rev[idx[0]]
        if not os.path.exists(clip['path']):
            return
        subprocess.Popen([
            'mpv', '--fullscreen', '--no-terminal',
            '--osd-level=1', '--hwdec=v4l2m2m',
            clip['path'],
        ])

    def _delete_clip(self):
        idx = self._clip_lb.curselection()
        if not idx:
            return
        clips_rev = list(reversed(self._clips))
        clip = clips_rev[idx[0]]
        try:
            os.remove(clip['path'])
        except OSError:
            pass
        self._refresh_clips()

    # ── WiFi ──────────────────────────────────────────────────────────────────

    def _scan_wifi(self):
        self._wifi_status.config(text='Scanning…', fg=C_AMBER)
        self.wifi.scan(callback=self._on_scan_done)

    def _on_scan_done(self, nets):
        self.root.after(0, self._populate_wifi_list)

    def _populate_wifi_list(self):
        BARS = ['▁', '▃', '▅', '▇']
        self._wifi_lb.delete(0, 'end')
        for n in self.wifi.last_networks:
            bar  = BARS[min(3, n['strength'] // 25)]
            lock = ' 🔒' if n.get('secure') else '   '
            star = ' ●' if n.get('in_use') else ''
            self._wifi_lb.insert('end', f'{bar} {n["ssid"]}{lock}{star}')
        self._refresh_wifi_status()

    def _on_wifi_select(self, _event):
        idx = self._wifi_lb.curselection()
        if not idx:
            return
        nets = self.wifi.last_networks
        if idx[0] >= len(nets):
            return
        net  = nets[idx[0]]
        ssid = net['ssid']
        if net.get('in_use'):
            return
        known = self.wifi.known_networks()
        if ssid in known:
            threading.Thread(target=lambda: self.wifi.connect_known(ssid),
                             daemon=True).start()
            self.root.after(4000, self._refresh_wifi_status)
        elif net.get('secure'):
            self._wifi_pending = ssid
            self._pw_entry.delete(0, 'end')
            self._pw_entry.focus_set()
        else:
            threading.Thread(target=lambda: self.wifi.connect(ssid),
                             daemon=True).start()
            self.root.after(4000, self._refresh_wifi_status)

    def _connect_with_pw(self):
        ssid = self._wifi_pending
        pw   = self._pw_entry.get()
        self._pw_entry.delete(0, 'end')
        if ssid and pw:
            threading.Thread(
                target=lambda: self.wifi.connect(ssid, pw),
                daemon=True
            ).start()
            self.root.after(6000, self._refresh_wifi_status)
        self._wifi_pending = None

    def _refresh_wifi_status(self):
        conn = self.wifi.current_connection()
        if conn:
            self._wifi_status.config(
                text=f"Connected: {conn['ssid']} ({conn['strength']}%)",
                fg=C_GREEN
            )
        else:
            self._wifi_status.config(text='Not connected', fg=C_DIM)

    # ── Panel slide animation ─────────────────────────────────────────────────

    def _slide_panel(self, panel, attr, current, target, done_cb=None):
        if current == target:
            if done_cb:
                done_cb()
            return
        step = SLIDE_STEP if target > current else -SLIDE_STEP
        nxt  = current + step
        if (step > 0 and nxt >= target) or (step < 0 and nxt <= target):
            nxt = target
        setattr(self, attr, nxt)
        r = panel.place_info()
        panel.place(x=nxt, y=int(r['y']), width=PANEL_W,
                    height=H - 2 * BAR_H)
        panel.lift()
        if nxt != target:
            self.root.after(SLIDE_MS,
                lambda: self._slide_panel(panel, attr, nxt, target, done_cb))
        elif done_cb:
            done_cb()

    def _toggle_wifi(self):
        if not self._wifi_open:
            self._wifi_open = True
            self._slide_panel(self.wifi_panel, '_wifi_x', self._wifi_x, 0)
            self._refresh_wifi_status()
        else:
            self._wifi_open = False
            self._slide_panel(self.wifi_panel, '_wifi_x', self._wifi_x, -PANEL_W)

    def _toggle_playback(self):
        if not self._play_open:
            self._play_open = True
            self._refresh_clips()
            self._slide_panel(self.play_panel, '_play_x',
                              self._play_x, W - PANEL_W)
        else:
            self._play_open = False
            self._slide_panel(self.play_panel, '_play_x', self._play_x, W)

    # ── Chrome toggle (tap center of video) ──────────────────────────────────

    def _on_tap_down(self, e):
        self._tap_x, self._tap_y, self._tap_t = e.x, e.y, time.monotonic()

    def _on_tap_up(self, e):
        if time.monotonic() - self._tap_t > 0.4:
            return
        if abs(e.x - self._tap_x) > 20 or abs(e.y - self._tap_y) > 20:
            return
        if W // 3 < e.x < 2 * W // 3:
            self._chrome = not self._chrome
            if self._chrome:
                self.top.place(x=0, y=0, width=W, height=BAR_H)
                self.bot.place(x=0, y=H - BAR_H, width=W, height=BAR_H)
            else:
                self.top.place_forget()
                self.bot.place_forget()

    # ── Power ─────────────────────────────────────────────────────────────────

    def _power_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title('')
        dlg.attributes('-fullscreen', False)
        dlg.geometry('260x120')
        dlg.configure(bg=C_PANEL)
        dlg.grab_set()
        dlg.resizable(False, False)

        tk.Label(dlg, text='Shut down?', bg=C_PANEL, fg=C_TEXT,
                 font=('DejaVu Sans', 14)).pack(pady=20)

        row = tk.Frame(dlg, bg=C_PANEL)
        row.pack()

        def do_shutdown():
            dlg.destroy()
            if self.pipeline.recording:
                self.pipeline.stop_recording()
            system.shutdown()

        _btn(row, 'Shut down', do_shutdown).pack(side='left', padx=10, ipadx=10, ipady=6)
        _btn(row, 'Cancel', dlg.destroy).pack(side='left', padx=10, ipadx=10, ipady=6)

    # ── Settings (capture resolution) ─────────────────────────────────────────

    # (label, width, height, fps) — capture size must match the HDMI source.
    RES_PRESETS = (
        ('1920 × 1080', 1920, 1080, '25/1'),
        ('1280 × 720',  1280, 720,  '25/1'),
        ('720 × 576 (PAL)', 720, 576, '25/1'),
    )

    def _settings_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title('')
        dlg.geometry('320x260')
        dlg.configure(bg=C_PANEL)
        dlg.grab_set()
        dlg.resizable(False, False)

        tk.Label(dlg, text='Capture resolution', bg=C_PANEL, fg=C_TEXT,
                 font=('DejaVu Sans', 14)).pack(pady=(14, 4))

        cur = tk.Label(
            dlg, text=f'now: {self.pipeline.width} × {self.pipeline.height}',
            bg=C_PANEL, fg=C_DIM, font=F_SMALL)
        cur.pack(pady=(0, 10))

        if self.pipeline.recording:
            tk.Label(dlg, text='stop recording to change',
                     bg=C_PANEL, fg=C_AMBER, font=F_SMALL).pack()

        def apply(w, h, fps):
            if self.pipeline.recording:
                return
            ok = self.pipeline.reconfigure(w, h, fps)
            if ok:
                # persist for next boot (resolution + fps)
                system.save_setting('DVR_WIDTH',  w)
                system.save_setting('DVR_HEIGHT', h)
                system.save_setting('DVR_FPS',    fps)
                # re-hand the preview window to the rebuilt pipeline
                self.root.after(150, self._attach_preview)
            dlg.destroy()

        for label, w, h, fps in self.RES_PRESETS:
            mark = '  ●' if (w == self.pipeline.width and
                             h == self.pipeline.height) else ''
            b = _btn(dlg, label + mark, lambda w=w, h=h, f=fps: apply(w, h, f))
            b.pack(fill='x', padx=24, pady=4, ipady=6)

        _btn(dlg, 'Close', dlg.destroy).pack(fill='x', padx=24, pady=(10, 4),
                                             ipady=4)
