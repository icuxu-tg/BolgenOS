#!/usr/bin/env bash
set -euo pipefail

# Helper for Arch build host: build AUR packages and create a local repo.
# Run as a REGULAR user (NOT root, makepkg forbids root):
#   ./prepare-aur-localrepo.sh
#   ./prepare-aur-localrepo.sh yay calamares
#   ./prepare-aur-localrepo.sh --repo-dir /srv/bolgenos-localrepo yay calamares

if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
  echo "Do not run as root (makepkg cannot run as root). Run as a regular user with sudo privileges." >&2
  exit 1
fi

REPO_DIR="/srv/bolgenos-localrepo"
if [[ "${1:-}" == "--repo-dir" ]]; then
  if [[ -z "${2:-}" ]]; then
    echo "Missing argument for --repo-dir" >&2
    exit 1
  fi
  REPO_DIR="$2"
  shift 2
fi

PKGS=("$@")
if [[ ${#PKGS[@]} -eq 0 ]]; then
  PKGS=(yay calamares)
fi

if [[ ! -d "$REPO_DIR" ]]; then
  if mkdir -p "$REPO_DIR" 2>/dev/null; then
    :
  else
    sudo mkdir -p "$REPO_DIR"
    sudo chown "$(id -u):$(id -g)" "$REPO_DIR"
  fi
elif [[ ! -w "$REPO_DIR" ]]; then
  sudo chown "$(id -u):$(id -g)" "$REPO_DIR"
fi

for pkg in "${PKGS[@]}"; do
  tmp="$(mktemp -d)"
  git clone --depth 1 "https://aur.archlinux.org/${pkg}.git" "$tmp/$pkg"
  (cd "$tmp/$pkg" && makepkg -s --noconfirm)
  cp "$tmp/$pkg"/*.pkg.tar.* "$REPO_DIR"/
  rm -rf "$tmp"
done

repo-add "$REPO_DIR/bolgenos-local.db.tar.gz" "$REPO_DIR"/*.pkg.tar.*
echo "Local repo ready: $REPO_DIR"
if [[ "$REPO_DIR" != "/srv/bolgenos-localrepo" ]]; then
  echo "Update pacman.conf [bolgenos-local] Server=file://$REPO_DIR before building."
fi
