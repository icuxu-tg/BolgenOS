#!/usr/bin/env bash
# shellcheck disable=SC2034

iso_name="bolgenos"
iso_label="BOLGENOS_$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y%m)"
iso_publisher="BolgenOS <https://bolgenos.local>"
iso_application="BolgenOS Live/Install ISO"
iso_version="$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y.%m.%d)"
install_dir="bolgenos"
buildmodes=('iso')
bootmodes=('bios.syslinux'
           'uefi.systemd-boot')
arch="x86_64"
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
airootfs_image_tool_options=('-comp' 'xz' '-Xbcj' 'x86' '-b' '1M' '-Xdict-size' '1M')
bootstrap_tarball_compression=('zstd' '-c' '-T0' '--auto-threads=logical' '--long' '-19')
file_permissions=(
  ["/etc/sudoers.d/99-bolgenos-live"]="0:0:440"
  ["/usr/local/bin/bolgenos-live-setup"]="0:0:755"
  ["/usr/local/bin/bolgenos-prepare-target"]="0:0:755"
  ["/usr/local/bin/bolgenos-install-de"]="0:0:755"
  ["/usr/local/bin/bolgenos-postinstall"]="0:0:755"
  ["/usr/local/bin/bolgenos-welcome"]="0:0:755"
  ["/usr/local/bin/bolgenos-updater"]="0:0:755"
  ["/usr/local/bin/bolgenos-pacman-init"]="0:0:755"
  ["/usr/local/bin/dash-shell"]="0:0:755"
  ["/usr/local/share/dash-shell/dash.py"]="0:0:755"
  ["/etc/skel/Desktop/Install-BolgenOS.desktop"]="0:0:755"
  ["/etc/skel/Desktop/OgenBrowse.desktop"]="0:0:755"
  ["/etc/skel/Desktop/Antivirus-Popova.desktop"]="0:0:755"
  ["/etc/skel/.config/autostart/bolgenos-welcome.desktop"]="0:0:755"
  ["/etc/skel/.config/autostart/picom.desktop"]="0:0:755"
  ["/etc/skel/.config/autostart/plank.desktop"]="0:0:755"
  ["/etc/skel/.config/caja/scripts/Проверить Антивирусом Попова"]="0:0:755"
)
