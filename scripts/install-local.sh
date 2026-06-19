#!/usr/bin/env bash
# install-local.sh — dev install of YazSes from the local repo using uv tool.
# Run from the repo root (1private/) or any subdirectory.
# Usage: bash scripts/install-local.sh [--with-overlay]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"
ENV_DIR="$HOME/.config/environment.d"
AUTOSTART_DIR="$HOME/.config/autostart"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[x]${NC} $*"; exit 1; }

WITH_OVERLAY=0
for arg in "$@"; do [[ "$arg" == "--with-overlay" ]] && WITH_OVERLAY=1; done

# ── 1. Detect X11/Wayland display ───────────────────────────────────────────
DETECTED_DISPLAY="${DISPLAY:-}"
DETECTED_XAUTH="${XAUTHORITY:-}"

if [[ -z "$DETECTED_DISPLAY" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    warn "No DISPLAY or WAYLAND_DISPLAY detected. Run this script from a desktop terminal."
fi

# ── 2. Stop & uninstall existing installation ────────────────────────────────
info "Stopping existing services..."
systemctl --user stop yazses.service 2>/dev/null || true
systemctl --user disable yazses.service 2>/dev/null || true

info "Uninstalling previous uv tool installation..."
uv tool uninstall yazses 2>/dev/null || true

# Drop any cached yazses wheel. uv keys its build cache on the version string, so
# a same-version source change (common during local iteration) would otherwise be
# served stale — the installed code would not match the working tree.
info "Clearing cached yazses build..."
uv cache clean yazses 2>/dev/null || true

# ── 3. Fresh install from local repo ────────────────────────────────────────
info "Installing YazSes from $REPO_ROOT ..."
if [[ $WITH_OVERLAY -eq 1 ]]; then
    uv tool install --force --reinstall --with "PySide6>=6.7" "$REPO_ROOT"
else
    uv tool install --force --reinstall "$REPO_ROOT"
fi

# ── 4. XDG autostart — makes DISPLAY available to the systemd user manager ──
# This runs at every graphical login and is the reliable cross-DE fix so that
# xdotool injection and the overlay work for any user without manual setup.
info "Installing XDG autostart entry (display environment import)..."
mkdir -p "$AUTOSTART_DIR"
cp "$REPO_ROOT/contrib/yazses-session.desktop" "$AUTOSTART_DIR/yazses-session.desktop"

# Also pin the current display immediately so the running session is covered
# without needing a re-login.
if [[ -n "$DETECTED_DISPLAY" ]]; then
    mkdir -p "$ENV_DIR"
    cat > "$ENV_DIR/yazses-display.conf" <<EOF
# Written by install-local.sh — updated on reinstall.
DISPLAY=$DETECTED_DISPLAY
XAUTHORITY=$DETECTED_XAUTH
EOF
    systemctl --user import-environment DISPLAY XAUTHORITY 2>/dev/null || true
fi

# ── 5. Install systemd unit file ────────────────────────────────────────────
info "Installing systemd unit file..."
mkdir -p "$SYSTEMD_DIR"
cp "$REPO_ROOT/contrib/yazses.service" "$SYSTEMD_DIR/yazses.service"
systemctl --user daemon-reload

# ── 6. Enable and start ──────────────────────────────────────────────────────
info "Enabling and starting yazses.service ..."
systemctl --user enable --now yazses.service

# ── 7. Verify ────────────────────────────────────────────────────────────────
echo ""
info "Service status:"
systemctl --user status yazses.service --no-pager -l | tail -8

echo ""
info "Done. $(yazses --version 2>/dev/null || echo 'Restart shell to refresh PATH')"
info "Run 'yazses status' to confirm IPC is up."
if [[ $WITH_OVERLAY -eq 0 ]]; then
    echo ""
    warn "Overlay not installed (PySide6 skipped). Re-run with --with-overlay to enable sonar rings."
fi
