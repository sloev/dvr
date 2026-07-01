#!/bin/bash
# dvr-provision.sh — runs ONCE on the very first boot (root still writable,
# after the stock partition resize). Enables read-only root, then reboots.
# The flag lives on the FAT partition so it survives the switch to read-only.
set -e

FLAG=/boot/firmware/.dvr-provisioned
[ -f "$FLAG" ] && exit 0

add_fstab() {   # $1 = full fstab line, $2 = unique match substring
    grep -qF "$2" /etc/fstab || echo "$1" >> /etc/fstab
}

# Volatile dirs as tmpfs so nothing writes to the card during normal use.
add_fstab "tmpfs /tmp     tmpfs defaults,noatime,nosuid,size=64m 0 0" " /tmp "
add_fstab "tmpfs /var/log tmpfs defaults,noatime,nosuid,size=32m 0 0" " /var/log "
add_fstab "tmpfs /var/tmp tmpfs defaults,noatime,nosuid,size=16m 0 0" " /var/tmp "

# Read-only root via overlayroot (tmpfs upper → writes discarded on reboot).
cat > /etc/overlayroot.conf <<'CONF'
overlayroot_cfgdisk="disabled"
overlayroot="tmpfs:swap=0,recurse=0"
CONF

# Rebuild the initramfs so the overlayroot hook picks up the new config.
echo -e "\033[2J\033[H"
echo -e "\033[91m  📼 RETRO DVR \033[0m\n"
echo -e "  Setting up the appliance for the first time..."
echo -e "  This takes about 1-2 minutes. \033[93mDO NOT POWER OFF.\033[0m\n"
update-initramfs -u

touch "$FLAG"
sync
systemctl reboot
