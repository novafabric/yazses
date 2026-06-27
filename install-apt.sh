#!/usr/bin/env bash
# YazSes APT installer for Debian/Ubuntu.
# Adds the YazSes APT repository, installs yazses, and enables the user service.
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[x]${NC} $*"; exit 1; }

PAGES_BASE="${YAZSES_APT_BASE_URL:-https://novafabric.github.io/yazses/apt}"
RAW_BASE="https://raw.githubusercontent.com/novafabric/yazses/gh-pages/apt"
KEYRING="/usr/share/keyrings/yazses.gpg"
SOURCE_LIST="/etc/apt/sources.list.d/yazses.list"
TMP_KEY="$(mktemp)"
trap 'rm -f "$TMP_KEY"' EXIT

echo ""
echo "  YazSes APT Installer"
echo "  Hold Space → speak → release → text appears anywhere"
echo ""

if ! command -v curl >/dev/null 2>&1; then
  info "Installing curl..."
  sudo apt-get update -qq
  sudo apt-get install -y curl ca-certificates gnupg
else
  sudo apt-get install -y -qq ca-certificates gnupg >/dev/null
fi

BASE_URL="$PAGES_BASE"
info "Checking APT repository at $BASE_URL ..."
if ! curl -fsSL "$BASE_URL/KEY.gpg" -o "$TMP_KEY"; then
  warn "GitHub Pages APT URL is not reachable yet; falling back to raw GitHub content."
  BASE_URL="$RAW_BASE"
  curl -fsSL "$BASE_URL/KEY.gpg" -o "$TMP_KEY" || error "Could not download YazSes APT signing key from GitHub Pages or raw GitHub."
fi

info "Installing APT signing key..."
sudo install -d -m 0755 /usr/share/keyrings
sudo rm -f "$KEYRING"
sudo gpg --batch --yes --dearmor -o "$KEYRING" "$TMP_KEY"
sudo chmod 0644 "$KEYRING"

info "Adding YazSes APT source: $BASE_URL"
echo "deb [signed-by=$KEYRING] $BASE_URL ./" | sudo tee "$SOURCE_LIST" >/dev/null

info "Updating package lists..."
sudo apt-get update

info "Installing YazSes..."
sudo apt-get install -y yazses

# The .deb declares libportaudio2 + pipx hard, but injection/clipboard are
# alternatives (xdotool | ydotool | wtype, xclip | wl-clipboard) so apt installs
# only the first. Install the full set explicitly so dictation works on BOTH X11
# (xdotool/xclip) and Wayland (wtype/ydotool/wl-clipboard) regardless of session.
# libportaudio2 is listed again for the belt-and-braces case. Tolerate any single
# package being absent on older releases — YazSes only needs one backend per role.
info "Installing audio + input/clipboard backends (X11 and Wayland)..."
for pkg in libportaudio2 xdotool ydotool wtype xclip wl-clipboard; do
  sudo apt-get install -y "$pkg" >/dev/null 2>&1 \
    && info "  installed $pkg" \
    || warn "  $pkg unavailable on this release (skipped)"
done

if ! groups "$USER" | grep -qw input; then
  info "Adding $USER to the input group for keyboard access..."
  sudo usermod -aG input "$USER"
  NEEDS_RELOGIN=1
else
  NEEDS_RELOGIN=0
fi

if command -v systemctl >/dev/null 2>&1; then
  info "Enabling YazSes user service..."
  systemctl --user daemon-reload || true
  systemctl --user enable yazses.service || true
  if [ "${NEEDS_RELOGIN:-0}" = "0" ]; then
    systemctl --user start yazses.service || true
  fi
fi

echo ""
echo "  ✓ YazSes installed via APT"
echo ""
if [ "${NEEDS_RELOGIN:-0}" = "1" ]; then
  warn "Log out and back in before using YazSes. The input group change needs a new login session."
fi

echo "  Test commands:"
echo "    yazses doctor"
echo "    yazses status"
echo ""
