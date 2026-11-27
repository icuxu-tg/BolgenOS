# BolgenOS

Arch-based live ISO + installer profile for **BolgenOS** (`bolgenos`) — «принципиально новой ОС» с нескучными обоями, OgenBrowse и Антивирусом Попова.

## Spec
- Base: Arch Linux (`archiso`), Live ISO (`bios.syslinux` с `splash.png`, `uefi.systemd-boot`) + `plymouth` splash
- Installer: Calamares с **выбором рабочего стола** (`MATE + Plank` офлайн по умолчанию, `KDE Plasma 6`, `XFCE`, `Cinnamon`, `GNOME` по сети), тема GRUB и fallback-установщик `archinstall`
- Live DE: MATE (одна верхняя панель `bolgenos.layout` + док `plank` + композитор `picom` + `Materia-dark` / `Papirus-Dark` + шрифты `Inter` и `JetBrains Mono`)
- Welcome: GTK3-приложение `bolgenos-welcome` (обои с превью, поиск/установка пакетов через `pacman`/`yay` и `Octopi`, автодетект NVIDIA, твики, Timeshift, автозапуск-тумблер)
- Apps & features:
  - `firefox` + `firefox-i18n-ru` («OgenBrowse» + `uBlock Origin` + стартовая страница)
  - `clamtk` («Антивирус Попова» + скрипт в контекстном меню Caja + `clamav-freshclam.service`)
  - `libreoffice-fresh` + `libreoffice-fresh-ru` + `hunspell-ru`, `vlc`, кодеки, PipeWire
  - `timeshift`, `snapper`, `snap-pac`, `grub-btrfs` (снэпшоты и откат из GRUB)
  - `qemu-guest-agent`, `spice-vdagent`, `virtualbox-guest-utils` (удобная работа в VM)
  - `yay`, `zram-generator`, `ufw`/`gufw`, `bluez`/`blueman`, `cups`/`system-config-printer`/`simple-scan`
- Packaging & CI: готовые `PKGBUILD` в `packaging/`, скрипт `release.sh` (ISO + `.sha256`) и `.github/workflows/build-iso.yml`

## Build (on Arch Linux x86_64 host)
1. Build local AUR repo for `yay` and `calamares` into `/srv/bolgenos-localrepo` as a **regular user** (not root):
```bash
./prepare-aur-localrepo.sh
```
2. Build ISO + SHA256 as root:
```bash
sudo pacman -S --needed archiso
sudo ./release.sh
```
Output ISO and `.sha256` will be in `./out/`.
