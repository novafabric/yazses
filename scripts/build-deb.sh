#!/usr/bin/env bash
# Build a .deb package for YazSes.
# Produces a small meta-package that installs system deps and sets up
# the systemd service. Python dependencies are installed via pipx from PyPI.
set -euo pipefail

VERSION=$(python3 -c "
import tomllib, pathlib
data = tomllib.load(pathlib.Path('pyproject.toml').open('rb'))
print(data['project']['version'])
")
ARCH=$(dpkg --print-architecture)
PKG="yazses_${VERSION}_${ARCH}"
STAGING=$(mktemp -d)
trap "rm -rf $STAGING" EXIT

echo "Building ${PKG}.deb ..."

# Systemd service (system-wide, pointing to /usr/bin/yazses-daemon)
mkdir -p "$STAGING/usr/lib/systemd/user"
sed 's|%h/.local/bin/yazses-daemon|/usr/bin/yazses-daemon|g' \
    contrib/yazses.service > "$STAGING/usr/lib/systemd/user/yazses.service"

# Example config
mkdir -p "$STAGING/usr/share/yazses"
cp examples/config.example.toml "$STAGING/usr/share/yazses/"

# DEBIAN metadata
mkdir -p "$STAGING/DEBIAN"

cat > "$STAGING/DEBIAN/control" <<EOF
Package: yazses
Version: ${VERSION}
Architecture: all
Maintainer: Mohsen Seyedkazemi Moghadam <mohsen.seyedkazemi@gmail.com>
Depends: python3 (>= 3.11), python3-pip, libportaudio2, pipx, xdotool | ydotool | wtype, xclip | wl-clipboard
Recommends: xdotool, xclip
Description: Local, offline voice dictation daemon for Linux
 Hold Space anywhere on your desktop, speak, then release Space.
 The transcribed text is injected into whatever application is focused.
 No internet required after initial model download. CPU-only inference.
 .
 Powered by faster-whisper (CTranslate2 backend).
Homepage: https://github.com/novafabric/yazses
EOF

cat > "$STAGING/DEBIAN/postinst" <<'EOF'
#!/bin/bash
set -e

if [ "$1" = "configure" ]; then
    # Install yazses Python package via pipx for each user who runs this
    # (or system-wide via pip if pipx is unavailable)
    if command -v pipx &>/dev/null; then
        CALLER="${SUDO_USER:-$USER}"
        if [ "$CALLER" != "root" ]; then
            su - "$CALLER" -c "pipx install yazses 2>/dev/null || pipx upgrade yazses"
            su - "$CALLER" -c "pipx ensurepath"
        fi
    else
        pip3 install --quiet yazses
        ln -sf "$(pip3 show yazses | awk '/^Location/{print $2}')/../../bin/yazses" /usr/bin/yazses 2>/dev/null || true
        ln -sf "$(pip3 show yazses | awk '/^Location/{print $2}')/../../bin/yazses-daemon" /usr/bin/yazses-daemon 2>/dev/null || true
    fi

    echo ""
    echo "YazSes installed."
    echo ""
    echo "Complete setup (run once per user):"
    echo "  sudo usermod -aG input \$USER   # allow keyboard access"
    echo "  Log out and back in"
    echo ""
    echo "Auto-start on login:"
    echo "  systemctl --user enable --now yazses.service"
    echo ""
    echo "Or use the interactive installer:"
    echo "  bash /usr/share/yazses/install.sh"
fi
EOF
chmod 755 "$STAGING/DEBIAN/postinst"

cat > "$STAGING/DEBIAN/prerm" <<'EOF'
#!/bin/bash
set -e
if [ "$1" = "remove" ]; then
    systemctl --user disable --now yazses.service 2>/dev/null || true
fi
EOF
chmod 755 "$STAGING/DEBIAN/prerm"

# Copy install.sh into the package for convenience
cp install.sh "$STAGING/usr/share/yazses/install.sh"

dpkg-deb --build "$STAGING" "${PKG}.deb"
echo "Built: ${PKG}.deb"
