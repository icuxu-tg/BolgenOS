# Приложения BolgenOS

Полный список того, что предустанавливается в Live/Install ISO (см. `packages.x86_64`) и что написано специально для BolgenOS.

## Собственные приложения BolgenOS

| Приложение | Команда / файл | Назначение |
| :--- | :--- | :--- |
| BolgenOS Welcome | `bolgenos-welcome` | GTK3-центр: обои, установка пакетов, драйверы, твики, информация о системе |
| BolgenOS Updater | `bolgenos-updater` | Сверка `/etc/bolgenos-release.sha256` с GitHub Releases, запуск обновления |
| GameHub | `bolgenos-gamehub` | Игровой центр: библиотека игр, установка Steam/Lutris/Wine/MangoHud/GameMode |
| OgenBrowse | `firefox` + policies | Брендированный браузер на базе Firefox с uBlock Origin и стартовой страницей |
| Антивирус Попова | `clamtk` + Caja-скрипт | Сканер ClamAV и проверка файлов из контекстного меню |
| dash-shell | `/usr/local/bin/dash-shell` | Интерактивная Python-оболочка в духе fish |
| shkit / shellmenu / daily_report | `/usr/local/share/dash-shell/` | POSIX-sh библиотека, меню запуска скриптов, git-отчёт |

## Рабочий стол и оформление

- MATE (`mate`, `mate-extra`), панель с layout `bolgenos`
- Plank (док), Picom (композитор)
- LightDM + `lightdm-gtk-greeter`
- Темы: `materia-gtk-theme`, `papirus-icon-theme`
- Шрифты: `ttf-dejavu`, `ttf-jetbrains-mono`, `inter-font`, `noto-fonts`, `noto-fonts-emoji`
- 16 обоев в `/usr/share/bolgenos/backgrounds/`
- Plymouth, GRUB/Syslinux темы, fastfetch

## Интернет и мультимедиа

- Firefox + `firefox-i18n-ru` (OgenBrowse)
- VLC
- PipeWire (`pipewire`, `pipewire-alsa`, `pipewire-pulse`, `pipewire-jack`, `wireplumber`)
- GStreamer (good / bad / ugly)
- `pavucontrol` — регулятор звука

## Файлы, архивы, печать, сканирование

- Caja, `gvfs`, `gvfs-mtp`, `gvfs-smb`, `gvfs-nfs`
- Engrampa (архиватор)
- `unzip`, `zip`, `p7zip`
- CUPS + `system-config-printer` + `cups-pdf`
- Simple Scan + `sane-airscan`

## Игры (через GameHub-каталог, устанавливаются по желанию)

`steam`, `lutris`, `heroic-games-launcher-bin`, `wine`, `winetricks`,
`protonup-qt`, `mangohud`, `lib32-mangohud`, `gamemode`, `vkbasalt`, `goverlay`.

## Разработка и утилиты

- `base-devel`, `git`
- Python 3 + `python-gobject`
- `nano`, `vim`, `htop`, `fastfetch`
- `curl`, `jq`, `rsync`
- `bash-completion`, `man-db`, `man-pages`, `less`
- `pciutils` (lspci)

## Система, безопасность, восстановление

- NetworkManager + `network-manager-applet`
- UFW + GUFW
- Timeshift, Snapper, `snap-pac`, `grub-btrfs`
- `zram-generator`, `power-profiles-daemon`
- Bluetooth (`bluez`, `bluez-utils`, `blueman`)
- `gnome-keyring`
- ClamAV/ClamTk

## Установка, разметка, загрузка

- Calamares (с выбором DE: MATE / KDE Plasma 6 / XFCE / Cinnamon / GNOME)
- `archinstall`, `arch-install-scripts`, GParted
- `grub`, `syslinux`, `efibootmgr`, `os-prober`, `memtest86+`
- Файловые системы: `dosfstools`, `e2fsprogs`, `btrfs-progs`, `ntfs-3g`, `gptfdisk`, `parted`, `mtools`, `squashfs-tools`
- `reflector`

## Виртуальные машины

- `qemu-guest-agent`, `spice-vdagent`, `virtualbox-guest-utils`
