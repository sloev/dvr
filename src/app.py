"""
DVR application — Tkinter + GStreamer.

GStreamer renders the live preview straight into a tk.Frame's X11 window (via
XID); Tkinter widgets sit on top as native X11 child windows — no compositing,
the picamera GPU-overlay trick.

Touch layout for the 800x480 / 4.3" panel — big targets, the record button is
the hero, secondary actions behind a slide-up menu:

  ┌── top status (46px) ──────────────────────────────────────────────┐
  │ ●sig 1080p25            HH:MM:SS:FF                          48°C  │
  ├── live preview (GStreamer) ───────────────────────────────────────┤
  │              red border shown while recording                     │
  ├── action row (88px) ──────────────────────────────────────────────┤
  │ ☰   [meters] 12.3GB        ▶PLAY    ⏏EJECT      ●  REC            │  idle
  │ ☰   [meters] …00:01:23   ⊕MARK 📷   ⏏          ■ STOP            │  recording
  └───────────────────────────────────────────────────────────────────┘
Menu (☰) → Wi-Fi · Settings · Info · Power.  Left panel = Wi-Fi, right = clips.
"""
import os
import sys
import time
import math
import threading
import subprocess
from datetime import datetime

import tkinter as tk
import io
from PIL import Image, ImageDraw

import system

# ── Geometry ──────────────────────────────────────────────────────────────────
W, H     = 800, 480
TOP_H    = 46
BOT_H    = 88
PANEL_W  = 300
PANEL_Y  = TOP_H
PANEL_H  = H - TOP_H - BOT_H
BORDER   = 5          # recording frame thickness
BH       = 72         # action-button height
BY       = (BOT_H - BH) // 2
SLIDE_STEP = 30
SLIDE_MS   = 16

# ── Colors ────────────────────────────────────────────────────────────────────
C_BG     = '#0d0d0d'
C_PANEL  = '#181818'
C_PANEL2 = '#242424'
C_TEXT   = '#e0e0e0'
C_DIM    = '#666666'
C_RED    = '#e03030'
C_REDDK  = '#2a0808'
C_GREEN  = '#30c040'
C_AMBER  = '#e0a020'
C_BLUE   = '#3080e0'
C_BORDER = '#303030'

F_MONO   = ('DejaVu Sans Mono', 13)
F_MONO_L = ('DejaVu Sans Mono', 18)
F_UI     = ('DejaVu Sans', 14)
F_SMALL  = ('DejaVu Sans', 11)
F_BTN    = ('DejaVu Sans', 16)
F_ICON   = ('DejaVu Sans', 20)
F_TILE   = ('DejaVu Sans', 18)

# Splash shown from launch until the preview is live.
SPLASH_CANDIDATES = (
    os.path.join(os.path.dirname(__file__), 'assets', 'splash.png'),
    os.path.join(os.path.dirname(__file__), '..', 'assets', 'splash-800x480.png'),
)
SPLASH_HOLD_MS = 2500


def _btn(parent, text, cmd, font=F_BTN, **kw):
    bg = kw.pop('bg', C_PANEL2)
    fg = kw.pop('fg', C_TEXT)
    abg = kw.pop('activebackground', C_BORDER)
    afg = kw.pop('activeforeground', 'white')
    b = tk.Button(parent, text=text, command=cmd,
                  bg=bg, fg=fg,
                  activebackground=abg, activeforeground=afg,
                  relief='flat', bd=0, cursor='hand2', font=font, **kw)
    return b


# ── Audio meter (PPM / VU + peak-hold + clip) ─────────────────────────────────
class Meter:
    """Dual dBFS meter with selectable PPM/VU ballistics, peak-hold and clip."""
    DB_MIN  = -54.0
    CLIP_DB = -0.5
    PPM_FALL = 13.0     # dB/s release (IEC-ish)
    HOLD_S   = 1.5
    HOLD_FALL = 14.0    # dB/s after the hold expires
    CLIP_HOLD = 3.0

    def __init__(self, canvas, x, y, w, h):
        self.c = canvas
        self.x, self.y, self.w, self.h = x, y, w, h
        self.bar_len = w - 30                       # leave room for clip LED
        self.disp = [self.DB_MIN, self.DB_MIN]
        self.hold = [self.DB_MIN, self.DB_MIN]
        self.hold_age = [0.0, 0.0]
        self.clip = [0.0, 0.0]

        bh = 13
        self.track, self.fill, self.peak = [], [], []
        for i in range(2):
            by = y + i * (bh + 4)
            self.track.append(self.c.create_rectangle(
                x, by, x + self.bar_len, by + bh, fill='#101010', outline=''))
            self.fill.append(self.c.create_rectangle(
                x, by, x, by + bh, fill=C_GREEN, outline=''))
            self.peak.append(self.c.create_line(
                x, by, x, by + bh, fill=C_TEXT, width=2))
        # clip LED
        lx = x + self.bar_len + 6
        self.led = self.c.create_rectangle(
            lx, y, lx + 18, y + 2 * bh + 4, fill='#200', outline=C_BORDER)
        # scale ticks/labels
        sy = y + 2 * bh + 7
        for db, lab in ((0, '0'), (-6, ''), (-12, '12'), (-20, ''),
                        (-40, '40')):
            tx = self._x(db)
            self.c.create_line(tx, sy, tx, sy + 4, fill=C_DIM)
            if lab:
                self.c.create_text(tx, sy + 9, text=lab, fill=C_DIM,
                                   font=('DejaVu Sans', 8))

    def _x(self, db):
        db = max(self.DB_MIN, min(0.0, db))
        return self.x + (db - self.DB_MIN) / (0 - self.DB_MIN) * self.bar_len

    @staticmethod
    def _col(db):
        return C_GREEN if db < -18 else (C_AMBER if db < -6 else C_RED)

    def update(self, peak, rms, mode, dt=0.05):
        for i in range(2):
            target = rms[i] if mode == 'VU' else peak[i]
            target = max(self.DB_MIN, min(0.0, target))
            if mode == 'VU':
                a = 1 - math.exp(-dt / 0.3)         # 300 ms one-pole
                self.disp[i] += (target - self.disp[i]) * a
            else:
                if target >= self.disp[i]:
                    self.disp[i] = target            # instant attack
                else:
                    self.disp[i] = max(target, self.disp[i] - self.PPM_FALL * dt)
            # peak hold
            if self.disp[i] >= self.hold[i]:
                self.hold[i] = self.disp[i]
                self.hold_age[i] = 0.0
            else:
                self.hold_age[i] += dt
                if self.hold_age[i] > self.HOLD_S:
                    self.hold[i] = max(self.disp[i],
                                       self.hold[i] - self.HOLD_FALL * dt)
            # clip latch
            if peak[i] >= self.CLIP_DB:
                self.clip[i] = self.CLIP_HOLD
            elif self.clip[i] > 0:
                self.clip[i] = max(0.0, self.clip[i] - dt)
        self._draw()

    def _draw(self):
        bh = 13
        for i in range(2):
            by = self.y + i * (bh + 4)
            self.c.coords(self.fill[i], self.x, by, self._x(self.disp[i]), by + bh)
            self.c.itemconfig(self.fill[i], fill=self._col(self.disp[i]))
            hx = self._x(self.hold[i])
            self.c.coords(self.peak[i], hx, by, hx, by + bh)
        clipped = self.clip[0] > 0 or self.clip[1] > 0
        self.c.itemconfig(self.led, fill=C_RED if clipped else '#200')


class DVRApp:
    def __init__(self, root, pipeline, storage, wifi):
        print(f"DVRApp: initializing on {W}x{H} (preview={os.environ.get('DVR_UI_PREVIEW')})...")
        self.root     = root
        self.pipeline = pipeline
        self.storage  = storage
        self.wifi     = wifi
        self._is_preview = os.environ.get('DVR_UI_PREVIEW') == '1'

        self._splash      = None
        self._splash_img  = None
        self._wifi_open   = False
        self._play_open   = False
        self._menu_open   = False
        self._clips       = []
        self._markers_path = None
        self._overlay     = None

        # Stopmotion state
        self._stopmotion_mode = False
        self._stopmotion_project_dir = None
        self._stopmotion_frame_count = 0
        self._onion_enabled = False
        self._onion_alpha = 0.5
        self._loop_previewing = False
        self._loop_images = []
        self._loop_frame_index = 0

        # meter state
        self._meter_mode = 'PPM'
        self._lvl_peak   = [Meter.DB_MIN, Meter.DB_MIN]
        self._lvl_rms    = [Meter.DB_MIN, Meter.DB_MIN]

        root.title('DVR')
        root.configure(bg='black')
        root.geometry(f'{W}x{H}+0+0')
        if os.environ.get('DVR_UI_PREVIEW') != '1':
            root.attributes('-fullscreen', True)
            # Use splash type on Pi to ensure it stays on top of any other UI
            try: root.wm_attributes('-type', 'splash')
            except: pass
        else:
            # On dev box, don't hijack the whole screen if not requested
            root.overrideredirect(True)

        self._build()
        self._show_splash()
        self._wire_pipeline()
        self._wire_storage()

        # Force initial render
        self.root.update()

        root.after(150, self._attach_preview)
        root.after(200, self._tick)
        root.after(50,  self._meter_tick)
        root.after(3000, self._poll_signal)
        root.after(50,  self._glib_pump)

    def _glib_pump(self):
        # No-op in preview mode (no GLib); harmless if the import fails.
        try:
            from gi.repository import GLib
            ctx = GLib.MainContext.default()
            n = 0
            while ctx.pending() and n < 10:
                ctx.iteration(False)
                n += 1
        except Exception:
            pass
        self.root.after(50, self._glib_pump)

    # ── Splash ────────────────────────────────────────────────────────────────

    def _show_splash(self):
        path = next((p for p in SPLASH_CANDIDATES if os.path.exists(p)), None)
        if not path:
            return
        try:
            self._splash_img = tk.PhotoImage(file=path)
        except tk.TclError:
            return
        self._splash = tk.Label(self.root, image=self._splash_img,
                                bg='black', bd=0, highlightthickness=0)
        self._splash.place(x=0, y=0, width=W, height=H)
        self._splash.lift()

    def _hide_splash(self):
        if self._splash is not None:
            self._splash.destroy()
            self._splash = self._splash_img = None

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        # video surface (GStreamer paints here)
        self.video_frame = tk.Frame(self.root, bg='black')
        self.video_frame.place(x=0, y=0, width=W, height=H)

        # recording border (4 strips around the preview, hidden until recording)
        self._rec_edges = []
        for geo in ((0, TOP_H, W, BORDER),
                    (0, H - BOT_H - BORDER, W, BORDER),
                    (0, TOP_H, BORDER, PANEL_H),
                    (W - BORDER, TOP_H, BORDER, PANEL_H)):
            f = tk.Frame(self.root, bg=C_RED)
            f._geo = geo
            self._rec_edges.append(f)

        self._build_top()
        self._build_action_row()
        self._build_menu()

        # side panels
        self._wifi_x = -PANEL_W
        self.wifi_panel = tk.Frame(self.root, bg=C_PANEL)
        self.wifi_panel.place(x=self._wifi_x, y=PANEL_Y, width=PANEL_W, height=PANEL_H)
        self._build_wifi_panel()

        self._play_x = W
        self.play_panel = tk.Frame(self.root, bg=C_PANEL)
        self.play_panel.place(x=self._play_x, y=PANEL_Y, width=PANEL_W, height=PANEL_H)
        self._build_play_panel()

        self._update_action_row()

        if self._is_preview:
            self._mock_preview_lbl = tk.Label(self.video_frame, bg='black')
            self._mock_preview_lbl.place(x=0, y=TOP_H, width=W, height=H - TOP_H - BOT_H)

    def _build_top(self):
        self.top = tk.Frame(self.root, bg=C_PANEL, height=TOP_H)
        self.top.place(x=0, y=0, width=W, height=TOP_H)
        self.top.pack_propagate(False)

        self._sig_canvas = tk.Canvas(self.top, width=14, height=14,
                                     bg=C_PANEL, highlightthickness=0)
        self._sig_canvas.pack(side='left', padx=(12, 5), pady=16)
        self._sig_dot = self._sig_canvas.create_oval(1, 1, 13, 13,
                                                      fill=C_RED, outline='')
        self._input_lbl = tk.Label(self.top, text='NO SIGNAL',
                                    bg=C_PANEL, fg=C_DIM, font=F_SMALL)
        self._input_lbl.pack(side='left', padx=2)

        # CI Debug label (bright white)
        tk.Label(self.top, text='CI-TEST', bg='#ffffff', fg='#000000',
                 font=F_SMALL, padx=4).pack(side='left', padx=10)

        tc_frame = tk.Frame(self.top, bg=C_PANEL)
        tc_frame.place(relx=0.5, rely=0.5, anchor='center')

        self._tc_lbl = tk.Label(tc_frame, text='00:00:00:00',
                                bg=C_PANEL, fg=C_TEXT, font=F_MONO_L)
        self._tc_lbl.pack(side='left')

        self._ntp_lbl = tk.Label(tc_frame, text='🕒',
                                 bg=C_PANEL, fg=C_DIM, font=F_SMALL)
        self._ntp_lbl.pack(side='left', padx=(6, 0))

        self._temp_lbl = tk.Label(self.top, text='--°C',
                                  bg=C_PANEL, fg=C_DIM, font=F_SMALL)
        self._temp_lbl.pack(side='right', padx=12)

    def _build_action_row(self):
        self.bot = tk.Frame(self.root, bg=C_PANEL, height=BOT_H)
        self.bot.place(x=0, y=H - BOT_H, width=W, height=BOT_H)

        # menu (far left)
        self._menu_btn = _btn(self.bot, '☰', self._open_menu, font=F_ICON)
        self._menu_btn.place(x=8, y=BY, width=86, height=BH)

        # meters + storage (left-center)
        self._meter_canvas = tk.Canvas(self.bot, width=232, height=BOT_H - 16,
                                       bg=C_PANEL, highlightthickness=0)
        self._meter_canvas.place(x=104, y=8)
        self._meter = Meter(self._meter_canvas, 2, 4, 232, BOT_H - 24)
        self._space_lbl = tk.Label(self.bot, text='No USB',
                                   bg=C_PANEL, fg=C_DIM, font=F_SMALL)
        self._space_lbl.place(x=104, y=BOT_H - 18)

        # hero REC (far right)
        self._rec_btn = tk.Button(
            self.bot, text='●  REC', font=('DejaVu Sans', 18, 'bold'),
            bg=C_PANEL, fg=C_RED, activebackground=C_REDDK, activeforeground=C_RED,
            relief='solid', bd=2, cursor='hand2', command=self._on_action_rec)
        self._rec_btn.place(x=W - 8 - 140, y=BY, width=140, height=BH)

        # eject (always present, left of REC)
        self._eject_btn = _btn(self.bot, '⏏', self._eject_usb, font=F_ICON)
        self._eject_btn.place(x=W - 8 - 140 - 8 - 78, y=BY, width=78, height=BH)

        # contextual slot: PLAY (idle) / GRAB (recording)
        slot_x = W - 8 - 140 - 8 - 78 - 8 - 78
        self._play_btn = _btn(self.bot, '▶', self._toggle_playback, font=F_ICON)
        self._grab_btn = _btn(self.bot, '📷', self._grab_still, font=F_ICON)
        self._mark_btn = _btn(self.bot, '⊕', self._place_marker, font=F_ICON)
        self._slot_x  = slot_x
        self._mark_x  = slot_x - 8 - 78

        # Stopmotion buttons
        self._onion_btn = _btn(self.bot, '🧅', self._toggle_onion_skin, font=F_ICON)
        self._onion_dec_btn = _btn(self.bot, '-', lambda: self._adjust_onion_alpha(-0.1), font=F_SMALL)
        self._onion_inc_btn = _btn(self.bot, '+', lambda: self._adjust_onion_alpha(0.1), font=F_SMALL)
        self._loop_btn  = _btn(self.bot, '🔁', self._toggle_loop_preview, font=F_ICON)
        self._compile_btn = _btn(self.bot, '🎬', self._compile_stopmotion_dialog, font=F_ICON)

    def _update_action_row(self):
        """Show idle vs recording vs stopmotion controls."""
        rec = self.pipeline.recording
        for b in (self._play_btn, self._grab_btn, self._mark_btn,
                  self._onion_btn, self._loop_btn, self._compile_btn,
                  self._onion_dec_btn, self._onion_inc_btn):
            b.place_forget()

        if self._stopmotion_mode:
            if self._onion_enabled:
                self._onion_btn.config(bg=C_BLUE, fg='white', text=f'🧅{int(self._onion_alpha*100)}%', font=F_SMALL)
                self._onion_btn.place(x=self._slot_x - 8 - 78, y=BY, width=46, height=BH)
                self._onion_dec_btn.place(x=self._slot_x - 8 - 78 + 50, y=BY, width=14, height=BH)
                self._onion_inc_btn.place(x=self._slot_x - 8 - 78 + 64, y=BY, width=14, height=BH)
            else:
                self._onion_btn.config(bg=C_PANEL2, fg=C_TEXT, text='🧅', font=F_ICON)
                self._onion_btn.place(x=self._slot_x - 8 - 78, y=BY, width=78, height=BH)
            self._loop_btn.place(x=self._slot_x, y=BY, width=78, height=BH)
            self._compile_btn.place(x=self._slot_x - 8 - 78 - 8 - 78, y=BY, width=78, height=BH)
            self._rec_btn.config(text='📷 CAPT', fg='white', bg=C_GREEN, relief='flat')
        elif rec:
            self._grab_btn.place(x=self._slot_x, y=BY, width=78, height=BH)
            self._mark_btn.place(x=self._mark_x, y=BY, width=78, height=BH)
            self._rec_btn.config(text='■ STOP', fg='white', bg=C_RED, relief='flat')
        else:
            self._play_btn.place(x=self._slot_x, y=BY, width=78, height=BH)
            self._rec_btn.config(text='●  REC', fg=C_RED, bg=C_PANEL, relief='solid')

    def _set_rec_border(self, on):
        for f in self._rec_edges:
            if on:
                x, y, w, h = f._geo
                f.place(x=x, y=y, width=w, height=h)
                f.lift()
            else:
                f.place_forget()

    # ── Slide-up menu ───────────────────────────────────────────────────────────

    def _build_menu(self):
        self.menu = tk.Frame(self.root, bg=C_BG)
        hdr = tk.Frame(self.menu, bg=C_BG)
        hdr.pack(fill='x', padx=14, pady=(10, 4))
        tk.Label(hdr, text='MENU', bg=C_BG, fg=C_TEXT, font=F_UI).pack(side='left')
        _btn(hdr, '✕', self._close_menu, font=F_ICON).pack(side='right', ipadx=6)

        grid = tk.Frame(self.menu, bg=C_BG)
        grid.pack(fill='both', expand=True, padx=14, pady=8)
        tiles = (('📶', 'Wi-Fi',      self._menu_wifi),
                 ('🎬', 'Stopmotion', self._menu_stopmotion),
                 ('⚙',  'Settings',   self._menu_settings),
                 ('ℹ',  'Info',       self._show_info),
                 ('⏻',  'Power',      self._menu_power))
        for idx, (icon, label, cmd) in enumerate(tiles):
            r, col = divmod(idx, 2)
            t = tk.Button(grid, text=f'{icon}\n{label}', command=cmd,
                          bg=C_PANEL2, fg=C_TEXT, activebackground=C_BORDER,
                          activeforeground='white', relief='flat', bd=0,
                          cursor='hand2', font=F_TILE, justify='center')
            t.grid(row=r, column=col, sticky='nsew', padx=8, pady=8)
        for i in range(3):
            grid.rowconfigure(i, weight=1)
        for i in range(2):
            grid.columnconfigure(i, weight=1)

    def _open_menu(self):
        self._menu_open = True
        self.menu.place(x=0, y=TOP_H, width=W, height=H - TOP_H)
        self.menu.lift()

    def _close_menu(self):
        self._menu_open = False
        self.menu.place_forget()

    def _menu_wifi(self):
        self._close_menu()
        self._toggle_wifi()

    def _menu_settings(self):
        self._close_menu()
        self._settings_dialog()

    def _menu_power(self):
        self._close_menu()
        self._power_dialog()

    # ── Wi-Fi panel ─────────────────────────────────────────────────────────────

    def _build_wifi_panel(self):
        f = self.wifi_panel
        hdr = tk.Frame(f, bg=C_PANEL)
        hdr.pack(fill='x', padx=8, pady=(8, 2))
        tk.Label(hdr, text='Wi-Fi', bg=C_PANEL, fg=C_TEXT, font=F_UI).pack(side='left')
        _btn(hdr, '✕', self._toggle_wifi, font=F_ICON).pack(side='right', ipadx=6)

        self._wifi_status = tk.Label(f, text='Not connected', bg=C_PANEL,
                                     fg=C_DIM, font=F_SMALL)
        self._wifi_status.pack(fill='x', padx=8, pady=2)

        self._wifi_lb = tk.Listbox(f, bg=C_PANEL2, fg=C_TEXT, selectbackground=C_BLUE,
                                   font=F_UI, relief='flat', bd=0, highlightthickness=1,
                                   highlightcolor=C_BORDER, activestyle='none',
                                   cursor='hand2')
        self._wifi_lb.pack(fill='both', expand=True, padx=8, pady=4)
        self._wifi_lb.bind('<ButtonRelease-1>', self._on_wifi_select)

        pw_f = tk.Frame(f, bg=C_PANEL)
        pw_f.pack(fill='x', padx=8, pady=2)
        tk.Label(pw_f, text='PW:', bg=C_PANEL, fg=C_DIM, font=F_SMALL).pack(side='left')
        self._pw_entry = tk.Entry(pw_f, show='*', bg=C_PANEL2, fg=C_TEXT,
                                  insertbackground=C_TEXT, relief='flat', font=F_UI)
        self._pw_entry.pack(side='left', fill='x', expand=True, ipady=6, padx=4)
        self._pw_entry.bind('<Return>', lambda _: self._connect_with_pw())

        row = tk.Frame(f, bg=C_PANEL)
        row.pack(fill='x', padx=8, pady=(4, 8))
        for t, c in (('↻ Scan', self._scan_wifi), ('Connect', self._connect_with_pw)):
            _btn(row, t, c).pack(side='left', fill='x', expand=True, padx=2, ipady=8)
        self._wifi_pending = None

    # ── Playback panel ──────────────────────────────────────────────────────────

    def _build_play_panel(self):
        f = self.play_panel
        hdr = tk.Frame(f, bg=C_PANEL)
        hdr.pack(fill='x', padx=8, pady=(8, 2))
        tk.Label(hdr, text='Recordings', bg=C_PANEL, fg=C_TEXT, font=F_UI).pack(side='left')
        _btn(hdr, '✕', self._toggle_playback, font=F_ICON).pack(side='right', ipadx=6)

        self._clip_lb = tk.Listbox(f, bg=C_PANEL2, fg=C_TEXT, selectbackground=C_BLUE,
                                   font=F_UI, relief='flat', bd=0, highlightthickness=1,
                                   highlightcolor=C_BORDER, activestyle='none',
                                   cursor='hand2')
        self._clip_lb.pack(fill='both', expand=True, padx=8, pady=4)
        self._clip_lb.bind('<Double-Button-1>', lambda _: self._play_clip())

        row = tk.Frame(f, bg=C_PANEL)
        row.pack(fill='x', padx=8, pady=(4, 8))
        for t, c in (('▶ Play', self._play_clip), ('↻', self._refresh_clips),
                     ('🗑 Delete', self._delete_clip)):
            _btn(row, t, c).pack(side='left', fill='x', expand=True, padx=2, ipady=8)

    # ── Pipeline / storage wiring ───────────────────────────────────────────────

    def _attach_preview(self):
        self.root.update_idletasks()
        xid = self.video_frame.winfo_id()
        self.pipeline.set_xid(xid)
        self.pipeline.play()
        if self._splash is not None:
            self.root.after(SPLASH_HOLD_MS, self._hide_splash)

    def _wire_pipeline(self):
        self.pipeline.on_level         = self._on_level
        self.pipeline.on_signal_change = self._on_signal_change
        self.pipeline.on_still_saved   = self._on_still_saved
        self.pipeline.on_error         = lambda m: print(f'[gst] {m}', file=sys.stderr)

    def _wire_storage(self):
        self.storage.on_drive_added   = self._on_drive_added
        self.storage.on_drive_removed = self._on_drive_removed

    # ── Ticks ────────────────────────────────────────────────────────────────────

    def _tick(self):
        now = datetime.now()
        ff = now.microsecond // 40000
        self._tc_lbl.config(text=now.strftime('%H:%M:%S') + f':{ff:02d}')
        self._temp_lbl.config(text=f'{system.cpu_temp():.0f}°C')

        if not hasattr(self, '_ntp_tick_cnt'):
            self._ntp_tick_cnt = 24
        self._ntp_tick_cnt += 1
        if self._ntp_tick_cnt >= 25:
            self._ntp_tick_cnt = 0
            synced = system.is_ntp_synced()
            self._ntp_lbl.config(fg=C_GREEN if synced else C_DIM)

        if self.pipeline.recording:
            self._rec_btn.config(text=f'■ {system.format_duration(self.pipeline.rec_elapsed)}')

        if self._is_preview:
            self._draw_mock_preview()

        self.root.after(200, self._tick)

    def _meter_tick(self):
        self._meter.update(self._lvl_peak, self._lvl_rms, self._meter_mode, 0.05)
        self.root.after(50, self._meter_tick)

    def _poll_signal(self):
        self._on_signal_change(self.pipeline.query_signal())
        self.root.after(3000, self._poll_signal)

    # ── Callbacks ────────────────────────────────────────────────────────────────

    def _on_level(self, pl, pr, rl, rr):
        self._lvl_peak = [pl, pr]
        self._lvl_rms  = [rl, rr]

    def _on_signal_change(self, has):
        if has:
            self._sig_canvas.itemconfig(self._sig_dot, fill=C_GREEN)
            self._input_lbl.config(text=f'{self.pipeline.width}×{self.pipeline.height}',
                                   fg=C_GREEN)
        else:
            self._sig_canvas.itemconfig(self._sig_dot, fill=C_RED)
            self._input_lbl.config(text='NO SIGNAL', fg=C_DIM)

    def _on_drive_added(self, dev, mp):
        free = self.storage.free_gb(mp)
        self._space_lbl.config(text=f'◉ {free:.1f} GB',
                               fg=C_AMBER if free < 5 else C_TEXT)
        self._markers_path = os.path.join(mp, 'markers.txt')
        self._refresh_clips()

    def _on_drive_removed(self, dev):
        self._space_lbl.config(text='No USB', fg=C_DIM)
        self._markers_path = None
        if self.pipeline.recording:
            self.pipeline.stop_recording()
            self._update_action_row()
            self._set_rec_border(False)

    def _on_still_saved(self, path):
        if self._stopmotion_mode and self._stopmotion_project_dir:
            try:
                img = Image.open(path)
                img = img.resize((800, 346), Image.NEAREST)
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                photo = tk.PhotoImage(data=buf.getvalue())
                self._loop_images.append(photo)
                if len(self._loop_images) > 40:
                    self._loop_images.pop(0)
            except Exception as e:
                print(f"Error caching frame for loop: {e}")

            if self._onion_enabled:
                self.pipeline.set_onion_skin(path, self._onion_alpha)
            self.root.after(0, lambda: self._flash(f'📷 frame {self._stopmotion_frame_count} saved', C_GREEN))
        else:
            self.root.after(0, lambda: self._flash('📷  saved'))

    # ── Recording ────────────────────────────────────────────────────────────────

    def _toggle_record(self):
        if self.pipeline.recording:
            self.pipeline.stop_recording()
        else:
            mp = self.storage.primary_mount
            if not mp:
                self._flash('No USB drive', C_AMBER)
                return
            self.pipeline.start_recording(mp)
        self._update_action_row()
        self._set_rec_border(self.pipeline.recording)

    def _place_marker(self):
        if not self.pipeline.recording or not self._markers_path:
            return
        ts = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        try:
            with open(self._markers_path, 'a') as f:
                f.write(f'{ts}  elapsed={self.pipeline.rec_elapsed:.1f}s\n')
            self._flash('⊕  marker')
        except OSError:
            pass

    def _grab_still(self):
        mp = self.storage.primary_mount
        if not mp:
            self._flash('No USB drive', C_AMBER)
            return
        stills = os.path.join(mp, 'stills')
        try:
            os.makedirs(stills, exist_ok=True)
        except OSError:
            pass
        path = os.path.join(stills, datetime.now().strftime('grab_%Y%m%d_%H%M%S.jpg'))
        self.pipeline.grab_still(path)

    # ── Stopmotion ───────────────────────────────────────────────────────────────

    def _on_action_rec(self):
        if self._stopmotion_mode:
            self._capture_frame()
        else:
            self._toggle_record()

    def _capture_frame(self):
        if not self._stopmotion_project_dir:
            self._flash('No stopmotion project', C_AMBER)
            return
        if self._loop_previewing:
            self._toggle_loop_preview()
        self._stopmotion_frame_count += 1
        path = os.path.join(self._stopmotion_project_dir, f'frame_{self._stopmotion_frame_count:04d}.jpg')
        self.pipeline.grab_still(path)

    def _toggle_onion_skin(self):
        if not self._stopmotion_mode:
            return
        self._onion_enabled = not self._onion_enabled
        if self._onion_enabled:
            if self._stopmotion_frame_count > 0 and self._stopmotion_project_dir:
                path = os.path.join(self._stopmotion_project_dir, f'frame_{self._stopmotion_frame_count:04d}.jpg')
                if os.path.exists(path):
                    self.pipeline.set_onion_skin(path, self._onion_alpha)
        else:
            self.pipeline.set_onion_skin(None)
        self._update_action_row()

    def _adjust_onion_alpha(self, delta):
        if not self._stopmotion_mode or not self._onion_enabled:
            return
        self._onion_alpha = round(max(0.1, min(0.9, self._onion_alpha + delta)), 1)
        self.pipeline.set_onion_alpha(self._onion_alpha)
        self._onion_btn.config(text=f'🧅{int(self._onion_alpha * 100)}%')

    def _toggle_loop_preview(self):
        if not self._stopmotion_mode:
            return
        self._loop_previewing = not self._loop_previewing
        if self._loop_previewing:
            if self._onion_enabled:
                self._toggle_onion_skin()
            self._loop_btn.config(bg=C_BLUE, fg='white')
            self._loop_lbl = tk.Label(self.root, bg='black')
            self._loop_lbl.place(x=0, y=TOP_H, width=W, height=H - TOP_H - BOT_H)
            self._loop_lbl.lift()

            if not self._loop_images and self._stopmotion_project_dir:
                import glob
                frames = sorted(glob.glob(os.path.join(self._stopmotion_project_dir, 'frame_*.jpg')))
                frames = frames[-40:]
                for f in frames:
                    try:
                        img = Image.open(f)
                        img = img.resize((800, 346), Image.NEAREST)
                        buf = io.BytesIO()
                        img.save(buf, format='PNG')
                        photo = tk.PhotoImage(data=buf.getvalue())
                        self._loop_images.append(photo)
                    except Exception as e:
                        print(f"Error loading frame for loop: {e}")

            self._loop_frame_index = -1
            self._animate_loop()
        else:
            self._loop_btn.config(bg=C_PANEL2, fg=C_TEXT)
            if hasattr(self, '_loop_lbl') and self._loop_lbl:
                self._loop_lbl.place_forget()
                self._loop_lbl.destroy()
                self._loop_lbl = None

    def _animate_loop(self):
        if not self._loop_previewing:
            return
        if not self._loop_images:
            self._flash('No frames captured yet', C_AMBER)
            self._toggle_loop_preview()
            return
        self._loop_frame_index = (self._loop_frame_index + 1) % len(self._loop_images)
        img = self._loop_images[self._loop_frame_index]
        self._loop_lbl.config(image=img)
        self._loop_lbl.image = img
        self.root.after(125, self._animate_loop)

    def _compile_stopmotion_dialog(self):
        if not self._stopmotion_mode or not self._stopmotion_project_dir:
            return
        if self._stopmotion_frame_count == 0:
            self._flash('No frames to compile', C_AMBER)
            return

        selected_fps = tk.IntVar(value=8)
        dlg = self._dialog('Compile Stopmotion', 340, 240)
        
        # Frame count label
        tk.Label(dlg, text=f'Compile {self._stopmotion_frame_count} frames\ninto an MP4 video.',
                 bg=C_PANEL, fg=C_TEXT, font=F_UI, justify='center').pack(pady=(12, 10))

        # Framerate Presets
        fps_frame = tk.Frame(dlg, bg=C_PANEL)
        fps_frame.pack(pady=10)

        fps_buttons = {}

        def select_fps(fps):
            selected_fps.set(fps)
            for f, btn in fps_buttons.items():
                if f == fps:
                    btn.config(bg=C_BLUE, fg='white')
                else:
                    btn.config(bg=C_PANEL2, fg=C_TEXT)

        for fps in [5, 8, 12, 24]:
            btn = _btn(fps_frame, f'{fps} FPS', lambda f=fps: select_fps(f), font=F_SMALL)
            btn.pack(side='left', padx=4, ipadx=6, ipady=4)
            fps_buttons[fps] = btn

        # Highlight default (8 FPS)
        select_fps(8)

        # Action row
        action_row = tk.Frame(dlg, bg=C_PANEL)
        action_row.pack(pady=(12, 0))

        def on_compile():
            fps_val = selected_fps.get()
            dlg.destroy()
            self._do_compile(fps_val)

        compile_btn = _btn(action_row, 'Compile', on_compile)
        compile_btn.config(bg=C_RED, fg='white', activebackground=C_REDDK)
        compile_btn.pack(side='left', padx=10, ipadx=12, ipady=8)

        cancel_btn = _btn(action_row, 'Cancel', dlg.destroy)
        cancel_btn.pack(side='left', padx=10, ipadx=12, ipady=8)

    def _do_compile(self, fps):
        mp = self.storage.primary_mount
        if not mp:
            self._flash('No USB drive', C_AMBER)
            return
        self._show_overlay('Compiling…', C_AMBER)
        now = datetime.now()
        out_name = now.strftime('stopmotion_%Y%m%d_%H%M%S.mp4')
        output_path = os.path.join(mp, out_name)
        self.pipeline.compile_stopmotion(
            self._stopmotion_project_dir,
            output_path,
            fps=fps,
            callback=self._on_compile_done
        )

    def _on_compile_done(self, success, err_msg):
        self._hide_overlay()
        if success:
            self.root.after(0, lambda: self._flash('🎬 stopmotion compiled successfully!', C_GREEN))
            self.root.after(0, self._refresh_clips)
        else:
            self.root.after(0, lambda: self._flash(f'Compilation failed: {err_msg}', C_RED))

    def _toggle_stopmotion_mode(self):
        if self.pipeline.recording:
            self._flash('Cannot enter stopmotion while recording', C_AMBER)
            return
        self._stopmotion_mode = not self._stopmotion_mode
        if self._stopmotion_mode:
            mp = self.storage.primary_mount
            if not mp:
                self._flash('No USB drive', C_AMBER)
                self._stopmotion_mode = False
                return
            now = datetime.now()
            proj_name = now.strftime('proj_%Y%m%d_%H%M%S')
            self._stopmotion_project_dir = os.path.join(mp, 'stopmotion', proj_name)
            try:
                os.makedirs(self._stopmotion_project_dir, exist_ok=True)
            except OSError:
                self._flash('Failed to create project dir', C_RED)
                self._stopmotion_mode = False
                return
            self._stopmotion_frame_count = 0
            self._onion_enabled = False
            self._loop_previewing = False
            self._loop_images = []
            self._loop_frame_index = 0
            self._onion_btn.config(bg=C_PANEL2, fg=C_TEXT)
            self._loop_btn.config(bg=C_PANEL2, fg=C_TEXT)
            self._flash('🎬 Stopmotion Mode active', C_GREEN)
        else:
            if self._loop_previewing:
                self._toggle_loop_preview()
            if self._onion_enabled:
                self._toggle_onion_skin()
            self.pipeline.set_onion_skin(None)
            self._stopmotion_project_dir = None
            self._stopmotion_frame_count = 0
            self._loop_images = []
            self._flash('Stopmotion Mode disabled')
        self._update_action_row()

    def _menu_stopmotion(self):
        self._close_menu()
        self._toggle_stopmotion_mode()

    def _draw_mock_preview(self):
        # Create a test pattern image
        img = Image.new('RGB', (800, 346), color='black')
        draw = ImageDraw.Draw(img)
        
        # Draw 8 vertical color bars
        bar_w = 800 // 8
        colors = [
            (220, 220, 220), # White
            (220, 220, 0),   # Yellow
            (0, 220, 220),   # Cyan
            (0, 220, 0),     # Green
            (220, 0, 220),   # Magenta
            (220, 0, 0),     # Red
            (0, 0, 220),     # Blue
            (20, 20, 20)     # Black/Dark grey
        ]
        for i, c in enumerate(colors):
            draw.rectangle([i * bar_w, 0, (i + 1) * bar_w, 346], fill=c)
            
        # Draw test circle
        draw.ellipse([300, 73, 500, 273], outline=(255, 255, 255), width=3)
        
        # If recording, draw a red "REC" indicator and elapsed time
        if self.pipeline.recording:
            draw.rectangle([10, 10, 150, 45], fill=(40, 0, 0), outline=(220, 30, 30), width=2)
            draw.ellipse([20, 22, 30, 32], fill=(220, 30, 30))
        
        # If onion skin is enabled and we have a last frame, blend it!
        if self._stopmotion_mode and self._onion_enabled and self._stopmotion_project_dir and self._stopmotion_frame_count > 0:
            path = os.path.join(self._stopmotion_project_dir, f'frame_{self._stopmotion_frame_count:04d}.jpg')
            if os.path.exists(path):
                try:
                    last_img = Image.open(path).convert('RGB').resize((800, 346), Image.NEAREST)
                    img = Image.blend(img, last_img, self._onion_alpha)
                except Exception as e:
                    print(f"Error blending onion skin in mock: {e}")
                    
        # Convert to PhotoImage and set it
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        self._mock_photo = tk.PhotoImage(data=buf.getvalue())
        self._mock_preview_lbl.config(image=self._mock_photo)

    # ── Eject (safe) ─────────────────────────────────────────────────────────────

    def _eject_usb(self):
        if not self.storage.drives:
            self._flash('No USB drive', C_AMBER)
            return
        msg = ('Stop recording and eject\nthe USB drive?'
               if self.pipeline.recording else 'Safely eject the USB drive?')
        self._confirm('Eject USB', msg, self._do_eject, yes='Eject')

    def _do_eject(self):
        self._show_overlay('Ejecting…', C_AMBER)
        threading.Thread(target=self._eject_worker, daemon=True).start()

    def _eject_worker(self):
        if self.pipeline.recording:
            self.pipeline.stop_recording()
            self.root.after(0, self._update_action_row)
            self.root.after(0, lambda: self._set_rec_border(False))
            time.sleep(0.6)
        ok = False
        for dev in list(self.storage.drives):
            if self.storage.eject(dev):
                ok = True
        self.root.after(0, lambda: self._eject_done(ok))

    def _eject_done(self, ok):
        if ok:
            self._space_lbl.config(text='Ejected', fg=C_GREEN)
            self._show_overlay('✓  Safe to remove', C_GREEN, dismiss_ms=4000)
        else:
            self._show_overlay('Eject failed', C_RED, dismiss_ms=2500)

    def _format_done(self, ok):
        self._hide_overlay()
        if ok:
            self._show_overlay('Format complete', C_GREEN, dismiss_ms=2500)
            self._refresh_clips()
        else:
            self._show_overlay('Format failed', C_RED, dismiss_ms=2500)

    # ── Playback ──────────────────────────────────────────────────────────────────

    def _refresh_clips(self):
        mp = self.storage.primary_mount
        self._clips = system.list_clips(mp) if mp else []
        self._clip_lb.delete(0, 'end')
        for c in reversed(self._clips):
            self._clip_lb.insert('end', f"  {c['name']}   {system.format_size(int(c['size_mb']*1e6))}")

    def _selected_clip(self):
        idx = self._clip_lb.curselection()
        if not idx:
            return None
        rev = list(reversed(self._clips))
        return rev[idx[0]] if idx[0] < len(rev) else None

    def _play_clip(self):
        clip = self._selected_clip()
        if not clip or not os.path.exists(clip['path']) or os.path.isdir(clip['path']):
            return
        subprocess.Popen(['mpv', '--fullscreen', '--no-terminal', '--osd-level=1',
                          '--hwdec=v4l2m2m', clip['path']])

    def _delete_clip(self):
        clip = self._selected_clip()
        if not clip:
            return
        self._confirm('Delete clip', f"Delete\n{clip['name']}?",
                      lambda: self._do_delete(clip), yes='Delete')

    def _do_delete(self, clip):
        try:
            if os.path.isdir(clip['path']):
                import shutil
                shutil.rmtree(clip['path'])
            else:
                os.remove(clip['path'])
        except OSError:
            pass
        self._refresh_clips()

    # ── Wi-Fi handlers ────────────────────────────────────────────────────────────

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

    def _on_wifi_select(self, _e):
        idx = self._wifi_lb.curselection()
        if not idx:
            return
        nets = self.wifi.last_networks
        if idx[0] >= len(nets):
            return
        net = nets[idx[0]]
        ssid = net['ssid']
        if net.get('in_use'):
            return
        if ssid in self.wifi.known_networks():
            threading.Thread(target=lambda: self.wifi.connect_known(ssid), daemon=True).start()
            self.root.after(4000, self._refresh_wifi_status)
        elif net.get('secure'):
            self._wifi_pending = ssid
            self._pw_entry.delete(0, 'end')
            self._pw_entry.focus_set()
        else:
            threading.Thread(target=lambda: self.wifi.connect(ssid), daemon=True).start()
            self.root.after(4000, self._refresh_wifi_status)

    def _connect_with_pw(self):
        ssid = self._wifi_pending
        pw = self._pw_entry.get()
        self._pw_entry.delete(0, 'end')
        if ssid and pw:
            threading.Thread(target=lambda: self.wifi.connect(ssid, pw), daemon=True).start()
            self.root.after(6000, self._refresh_wifi_status)
        self._wifi_pending = None

    def _refresh_wifi_status(self):
        conn = self.wifi.current_connection()
        if conn:
            self._wifi_status.config(text=f"Connected: {conn['ssid']} ({conn['strength']}%)",
                                     fg=C_GREEN)
        else:
            self._wifi_status.config(text='Not connected', fg=C_DIM)

    # ── Panel slides ───────────────────────────────────────────────────────────────

    def _slide_panel(self, panel, attr, current, target, done=None):
        if current == target:
            if done:
                done()
            return
        step = SLIDE_STEP if target > current else -SLIDE_STEP
        nxt = current + step
        if (step > 0 and nxt >= target) or (step < 0 and nxt <= target):
            nxt = target
        setattr(self, attr, nxt)
        panel.place(x=nxt, y=PANEL_Y, width=PANEL_W, height=PANEL_H)
        panel.lift()
        if nxt != target:
            self.root.after(SLIDE_MS, lambda: self._slide_panel(panel, attr, nxt, target, done))
        elif done:
            done()

    def _toggle_wifi(self):
        if not self._wifi_open:
            self._wifi_open = True
            self._slide_panel(self.wifi_panel, '_wifi_x', self._wifi_x, 0)
            self._scan_wifi()
            self._refresh_wifi_status()
        else:
            self._wifi_open = False
            self._slide_panel(self.wifi_panel, '_wifi_x', self._wifi_x, -PANEL_W)

    def _toggle_playback(self):
        if not self._play_open:
            self._play_open = True
            self._refresh_clips()
            self._slide_panel(self.play_panel, '_play_x', self._play_x, W - PANEL_W)
        else:
            self._play_open = False
            self._slide_panel(self.play_panel, '_play_x', self._play_x, W)

    # ── Settings ────────────────────────────────────────────────────────────────────

    RES_PRESETS = (
        ('1920 × 1080', 1920, 1080, '25/1'),
        ('1280 × 720',  1280, 720,  '25/1'),
        ('720 × 576 (PAL)', 720, 576, '25/1'),
    )

    def _settings_dialog(self):
        mp = self.storage.primary_mount
        h_dim = 480 if mp else 380
        dlg = self._dialog('Settings', 360, h_dim)
        body = tk.Frame(dlg, bg=C_PANEL)
        body.pack(fill='both', expand=True, padx=20, pady=6)

        tk.Label(body, text='Capture resolution', bg=C_PANEL, fg=C_TEXT,
                 font=F_UI).pack(pady=(4, 2))
        tk.Label(body, text=f'now: {self.pipeline.width} × {self.pipeline.height}',
                 bg=C_PANEL, fg=C_DIM, font=F_SMALL).pack()
        if self.pipeline.recording:
            tk.Label(body, text='stop recording to change', bg=C_PANEL,
                     fg=C_AMBER, font=F_SMALL).pack()

        def apply(w, h, fps):
            if self.pipeline.recording:
                return
            if self.pipeline.reconfigure(w, h, fps):
                system.save_setting('DVR_WIDTH', w)
                system.save_setting('DVR_HEIGHT', h)
                system.save_setting('DVR_FPS', fps)
                self.root.after(150, self._attach_preview)
            dlg.destroy()

        for label, w, h, fps in self.RES_PRESETS:
            mark = '  ●' if (w == self.pipeline.width and h == self.pipeline.height) else ''
            _btn(body, label + mark, lambda w=w, h=h, f=fps: apply(w, h, f)).pack(
                fill='x', pady=3, ipady=8)

        tk.Label(body, text='Audio meters', bg=C_PANEL, fg=C_TEXT,
                 font=F_UI).pack(pady=(12, 2))
        mrow = tk.Frame(body, bg=C_PANEL)
        mrow.pack(fill='x')

        def set_mode(m):
            self._meter_mode = m
            dlg.destroy()
        for m in ('PPM', 'VU'):
            mark = '  ●' if self._meter_mode == m else ''
            _btn(mrow, m + mark, lambda m=m: set_mode(m)).pack(
                side='left', fill='x', expand=True, padx=3, ipady=8)

        if mp:
            tk.Label(body, text='Storage formatting', bg=C_PANEL, fg=C_TEXT,
                     font=F_UI).pack(pady=(12, 2))
            def do_format():
                dlg.destroy()
                dev = next((d for d, m in self.storage.drives.items() if m == mp), None)
                if not dev:
                    self._show_overlay('No USB dev found', C_RED, dismiss_ms=2500)
                    return
                def on_confirm():
                    self._show_overlay('Formatting…', C_AMBER)
                    def format_worker():
                        ok = self.storage.format_usb(dev, 'DVR')
                        self.root.after(0, lambda: self._format_done(ok))
                    threading.Thread(target=format_worker, daemon=True).start()
                self._confirm('Format USB', 'Format USB drive as exFAT?\nALL recordings will be deleted.', on_confirm, yes='Format')
            _btn(body, 'Format USB', do_format, bg=C_RED, fg='white', activebackground=C_REDDK).pack(
                fill='x', pady=3, ipady=8)

        _btn(body, 'Close', dlg.destroy).pack(fill='x', pady=(12, 4), ipady=6)

    def _show_info(self):
        self._close_menu()
        dlg = self._dialog('Info', 380, 320)
        body = tk.Frame(dlg, bg=C_PANEL)
        body.pack(fill='both', expand=True, padx=22, pady=10)

        conn = self.wifi.current_connection()
        mp = self.storage.primary_mount
        rows = [
            ('IP address', conn['ip'] if conn else '—'),
            ('Wi-Fi',      f"{conn['ssid']} ({conn['strength']}%)" if conn else 'not connected'),
            ('Capture',    f'{self.pipeline.width} × {self.pipeline.height} @ {self.pipeline.fps}'),
            ('Signal',     'present' if self.pipeline.query_signal() else 'none'),
            ('Storage',    f'{self.storage.free_gb(mp):.1f} GB free' if mp else 'no USB'),
            ('CPU temp',   f'{system.cpu_temp():.0f} °C'),
            ('Uptime',     system.format_duration(system.uptime_seconds())),
        ]
        for k, v in rows:
            r = tk.Frame(body, bg=C_PANEL)
            r.pack(fill='x', pady=3)
            tk.Label(r, text=k, bg=C_PANEL, fg=C_DIM, font=F_SMALL, width=12,
                     anchor='w').pack(side='left')
            tk.Label(r, text=v, bg=C_PANEL, fg=C_TEXT, font=F_UI, anchor='w').pack(side='left')
        _btn(body, 'Close', dlg.destroy).pack(fill='x', pady=(14, 2), ipady=6)

    def _power_dialog(self):
        dlg = self._dialog('Power', 300, 180)
        tk.Label(dlg, text='Shut down?', bg=C_PANEL, fg=C_TEXT,
                 font=('DejaVu Sans', 16)).pack(pady=22)
        row = tk.Frame(dlg, bg=C_PANEL)
        row.pack()

        def do_shutdown():
            dlg.destroy()
            if self.pipeline.recording:
                self.pipeline.stop_recording()
            system.shutdown()
        _btn(row, 'Shut down', do_shutdown).pack(side='left', padx=10, ipadx=12, ipady=10)
        _btn(row, 'Cancel', dlg.destroy).pack(side='left', padx=10, ipadx=12, ipady=10)

    # ── Small UI helpers ──────────────────────────────────────────────────────────

    def _dialog(self, title, w, h):
        dlg = tk.Toplevel(self.root)
        dlg.title('')
        dlg.configure(bg=C_PANEL)
        dlg.geometry(f'{w}x{h}+{(W-w)//2}+{(H-h)//2}')
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.bind('<Escape>', lambda _: dlg.destroy())
        tk.Label(dlg, text=title, bg=C_PANEL, fg=C_DIM, font=F_SMALL).pack(pady=(8, 0))
        return dlg

    def _confirm(self, title, msg, on_yes, yes='OK'):
        dlg = self._dialog(title, 320, 200)
        tk.Label(dlg, text=msg, bg=C_PANEL, fg=C_TEXT, font=F_UI,
                 justify='center').pack(pady=18)
        row = tk.Frame(dlg, bg=C_PANEL)
        row.pack()

        def yes_cmd():
            dlg.destroy()
            on_yes()
        b = _btn(row, yes, yes_cmd)
        b.config(bg=C_RED, fg='white', activebackground=C_REDDK)
        b.pack(side='left', padx=10, ipadx=12, ipady=10)
        _btn(row, 'Cancel', dlg.destroy).pack(side='left', padx=10, ipadx=12, ipady=10)

    def _flash(self, msg, color=C_GREEN):
        lbl = tk.Label(self.root, text=msg, bg=C_PANEL, fg=color,
                       font=('DejaVu Sans', 16, 'bold'), padx=20, pady=10)
        lbl.place(relx=0.5, y=TOP_H + 24, anchor='n')
        lbl.lift()
        self.root.after(1200, lbl.destroy)

    def _show_overlay(self, msg, color=C_TEXT, dismiss_ms=None):
        if self._overlay is not None:
            self._overlay.destroy()
        ov = tk.Frame(self.root, bg=C_BG)
        ov.place(x=0, y=0, width=W, height=H)
        tk.Label(ov, text=msg, bg=C_BG, fg=color,
                 font=('DejaVu Sans', 26, 'bold')).place(relx=0.5, rely=0.5, anchor='center')
        ov.bind('<Button-1>', lambda _e: self._hide_overlay())
        ov.lift()
        self._overlay = ov
        if dismiss_ms:
            self.root.after(dismiss_ms, self._hide_overlay)

    def _hide_overlay(self):
        if self._overlay is not None:
            self._overlay.destroy()
            self._overlay = None
