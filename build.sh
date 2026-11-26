#!/usr/bin/env bash
set -euo pipefail

# Build BolgenOS ISO on an Arch Linux host.
# 1. As a regular user: ./prepare-aur-localrepo.sh
# 2. As root:           sudo ./build.sh

PROFILE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="${PROFILE_DIR}/work"
OUT_DIR="${PROFILE_DIR}/out"
LOCAL_REPO_DB="/srv/bolgenos-localrepo/bolgenos-local.db.tar.gz"

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run as root: sudo ./build.sh" >&2
  exit 1
fi

if ! command -v mkarchiso >/dev/null 2>&1; then
  echo "mkarchiso not found. Install archiso: pacman -S archiso" >&2
  exit 1
fi

if grep -q '^\[bolgenos-local\]' "${PROFILE_DIR}/pacman.conf" && [[ ! -f "$LOCAL_REPO_DB" ]]; then
  echo "Local AUR repo not found at $LOCAL_REPO_DB." >&2
  echo "Run ./prepare-aur-localrepo.sh as a regular user first (builds yay and calamares)." >&2
  exit 1
fi

rm -rf "$WORK_DIR"
mkdir -p "$OUT_DIR"

mkarchiso -v -w "$WORK_DIR" -o "$OUT_DIR" "$PROFILE_DIR"
echo "ISO built in: $OUT_DIR"
