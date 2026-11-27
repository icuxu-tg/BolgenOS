#!/usr/bin/env bash
set -euo pipefail

# Build release ISO + SHA256 checksum on an Arch Linux host.
# Prerequisite: run ./prepare-aur-localrepo.sh as a regular user first.
# Run as root: sudo ./release.sh

PROFILE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${PROFILE_DIR}/out"
RELEASE_HASH_FILE="${PROFILE_DIR}/airootfs/etc/bolgenos-release.sha256"

mkdir -p "$(dirname -- "$RELEASE_HASH_FILE")" "$OUT_DIR"

# Compute deterministic SHA256 of the config tree before packing airootfs.
RELEASE_HASH="$(
  cd "$PROFILE_DIR"
  find airootfs packages.x86_64 profiledef.sh -type f \
    ! -path 'airootfs/etc/bolgenos-release.sha256' \
    ! -path '*/__pycache__/*' \
    ! -name '*.pyc' \
    -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}'
)"

printf '%s\n' "$RELEASE_HASH" > "$RELEASE_HASH_FILE"
printf '%s\n' "$RELEASE_HASH" > "${PROFILE_DIR}/RELEASE_SHA256.txt"
printf '%s\n' "$RELEASE_HASH" > "${OUT_DIR}/RELEASE_SHA256.txt"
echo "Release config SHA256: $RELEASE_HASH"

"${PROFILE_DIR}/build.sh"

for iso in "${OUT_DIR}"/*.iso; do
  [ -f "$iso" ] || continue
  sha256sum "$iso" > "${iso}.sha256"
  echo "Checksum written: ${iso}.sha256"
done
