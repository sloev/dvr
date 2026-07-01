# Alternative Buildchain Plan

The current `pi-gen` buildchain compiles the entire Debian/Raspbian operating system from scratch using `debootstrap` and multi-stage `chroot` environments. This takes nearly an hour on GitHub Actions, wastes CI resources, and is overly complicated for a single-app appliance.

To achieve a **faster compiling OS** (faster CI builds) and a **faster booting OS** (less runtime overhead), here are three alternative buildchains, ordered by recommendation.

---

## Option 1: Base-Image Mutation (Recommended)
Instead of building Raspbian from scratch, we download the official pre-built Raspberry Pi OS Lite image, mount it, inject our app and dependencies, and shrink it back down.

* **Build Time:** ~3–5 minutes (down from ~50 minutes).
* **Boot Time:** ~10 seconds (using our existing systemd masking).
* **Compatibility:** 100% compatible. Retains the official Raspberry Pi kernel, DRM, and GStreamer `v4l2h264enc` hardware encoders.
* **Tooling:** A single bash script using `losetup`, `qemu-user-static` (for chroot), and `pishrink`. Alternatively, HashiCorp `Packer` with the `packer-builder-arm` plugin.

### Execution Steps:
1. Remove the `pi-gen` submodule.
2. Create a small CI script that `wget`s the latest official `raspios-lite-armhf.img.xz`.
3. Mount the image partitions via `losetup`.
4. `chroot` into the image and run `apt-get install` for Weston, GStreamer, and Python.
5. Copy the DVR app to `/opt/dvr`.
6. Unmount and run `pishrink.sh` to strip empty space and compress it for distribution.

---

## Option 2: Alpine Linux
Alpine Linux is built around `musl` libc and `BusyBox`. It is incredibly lightweight and uses `OpenRC` instead of `systemd`.

* **Build Time:** ~2 minutes (just extracting tarballs and `apk add`).
* **Boot Time:** ~3–5 seconds (OpenRC has almost zero overhead).
* **Tooling:** A script building a custom `.apkovl` (Alpine overlay) or using `alpine-make-rootfs`.
* **Caveat:** Because it uses `musl` instead of `glibc`, we must verify that the proprietary Raspberry Pi camera stack and hardware-accelerated GStreamer plugins compile and function correctly.

### Execution Steps:
1. Use the Alpine Linux Raspberry Pi release tarball.
2. Create an `apkovl.tar.gz` containing our `main.py`, Weston kiosk config, and an `/etc/local.d/dvr.start` init script.
3. Repackage the boot partition. 
4. The entire OS runs in RAM (tmpfs) by default, completely eliminating the need for `overlayroot` or read-only SD scripts.

---

## Option 3: Buildroot
Buildroot is the industry standard for true embedded Linux appliances. It compiles the cross-compiler, kernel, and every single userspace library from source code to create a hyper-minimal firmware image.

* **Build Time:** ~45 minutes initially, but **<2 minutes** on CI if `ccache` and `dl/` directories are heavily cached.
* **Boot Time:** <3 seconds.
* **Tooling:** `buildroot` with a custom `defconfig`.
* **Caveat:** High complexity. We would need to manage Buildroot `.mk` files for any Python packages or GStreamer plugins not included in the mainline tree.

### Execution Steps:
1. Clone the `buildroot` repository.
2. Run `make raspberrypi2_defconfig`.
3. Enter `make menuconfig` and enable GStreamer1, Python3, Tkinter, and Wayland/Weston.
4. Add the DVR source code as a custom `BR2_ROOTFS_OVERLAY`.
5. Run `make` to generate a tiny `sdcard.img` (often < 150MB total).
