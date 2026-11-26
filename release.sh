#!/usr/bin/env bash
set -euo pipefail

# Build release ISO + SHA256 checksum on an Arch Linux host.
# Prerequisite: run ./prepare-aur-localrepo.sh as a regular user first.
# Run as root: sudo ./release.sh

PROFILE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${PROFILE_DIR}/out"

"${PROFILE_DIR}/build.sh"

for iso in "${OUT_DIR}"/*.iso; do
  [ -f "$iso" ] || continue
  sha256sum "$iso" > "${iso}.sha256"
  echo "Checksum written: ${iso}.sha256"
done
