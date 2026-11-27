#!/usr/bin/env bash
set -e -u

cat << 'OSREL' > /etc/os-release
NAME="BolgenOS"
PRETTY_NAME="BolgenOS (Based on Arch Linux)"
ID=bolgenos
ID_LIKE=arch
BUILD_ID=rolling
ANSI_COLOR="38;2;23;147;209"
HOME_URL="https://github.com/icuxu-tg/BolgenOS"
DOCUMENTATION_URL="https://github.com/icuxu-tg/BolgenOS"
SUPPORT_URL="https://github.com/icuxu-tg/BolgenOS"
BUG_REPORT_URL="https://github.com/icuxu-tg/BolgenOS/issues"
LOGO=bolgenos
OSREL
cp -f /etc/os-release /usr/lib/os-release
