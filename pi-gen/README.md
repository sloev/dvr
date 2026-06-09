# DVR image build (pi-gen)

Reproducible build of the DVR appliance image: **Raspberry Pi OS Bookworm,
32-bit (armhf) Lite** + the DVR app, configured for fast boot and a read-only
root. Runs on Pi 2B and 3B.

## Build

```bash
cd pi-gen
./build.sh
```

`build.sh` clones pi-gen (pinned to the `bookworm`/armhf branch), stages
`../setup`, `../systemd`, and `../src` into the custom stage (single source of
truth — nothing is duplicated by hand), and runs the Docker build. Output:

```
pi-gen/pi-gen-src/deploy/dvr-*.img.xz
```

Build host needs Docker (and, on x86, `qemu-user-static` + `binfmt-support`
for armhf emulation — pi-gen's Docker image registers binfmt automatically on
most hosts). Edit `config` first to set `FIRST_USER_PASS` / locale / country.

## Flash

Raspberry Pi Imager → "Use custom image" → pick the `.img.xz`. Set Wi-Fi,
country, and hostname in the gear menu if you want them seeded. Or:

```bash
xzcat pi-gen-src/deploy/dvr-*.img.xz | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync
```

## What the image does on boot

- **First power-on (writable):** stock partition resize runs, then
  `dvr-provision.service` enables overlayroot (read-only root) + tmpfs for
  `/tmp`, `/var/log`, `/var/tmp`, rebuilds the initramfs, and reboots **once**.
  This is the only non-instant boot, and only on a freshly flashed card.
- **Every boot after:** root is **read-only** (writes go to a RAM overlay and
  vanish on reboot — safe to just pull the power). `tc358743.service` injects
  the EDID and sets the capture format, then `getty` autologins on tty1 and
  `.bash_profile` runs `startx`, which launches `/opt/dvr/main.py` fullscreen
  (auto-restarted if it ever exits). No display manager, no desktop.

## Boot-speed measures baked in

- `NetworkManager-wait-online` and `systemd-networkd-wait-online` **masked** —
  the app never waits for the network; Wi-Fi connects asynchronously.
- Masked: bluetooth, hciuart, ModemManager, avahi, triggerhappy, dphys-swapfile,
  rpi-eeprom-update, rfkill, the apt/man-db/e2scrub timers.
- `config.txt`: `disable_splash`, `boot_delay=0`, `initial_turbo=30`,
  `dtoverlay=disable-bt`.
- `cmdline.txt`: `quiet loglevel=3 logo.nologo fsck.mode=skip noswap`
  (fsck is safe to skip — root is read-only).
- Lite base + no display manager → the critical path is essentially
  kernel → tc358743 init → startx → app.

Check it on the device with `systemd-analyze` and `systemd-analyze blame`.

## Persistent Wi-Fi on a read-only root

NetworkManager's connection dir lives on the tmpfs overlay, so it's wiped each
reboot. To keep the "growing list of hotspots":

- After a successful connect, the app calls `sudo dvr-wifi-save` (the only
  command it's allowed to run as root) which mirrors the NM keyfiles to
  `/boot/firmware/dvr-wifi/` on the **writable FAT partition**.
- On the next boot, `dvr-wifi-restore.service` copies them back into NM with
  the required `600 root` perms, before NetworkManager starts.

## Notes

- Recordings always go to **USB**, never the SD card — the read-only root never
  fills up and the card lasts.
- To edit a provisioned card, boot it and run `sudo overlayroot-chroot` for a
  temporary writable shell, or re-flash.
- Resolution and other knobs are set in **`/boot/firmware/dvr.env`** — edit it
  on the SD card from any computer, no rebuild needed. Capture resolution must
  match what your HDMI source sends (e.g. set 1280×720 for a 720p source on the
  2B). Sourced by `.xinitrc` at launch.
