#!/usr/bin/env bash
# Build an unsigned YazSes .dmg on macOS.
#
# Steps:
#   1. Resolve runtime deps with uv (pulls PyObjC + rumps via env markers).
#   2. Install PyInstaller and create-dmg (build-only deps; not in pyproject).
#   3. Run PyInstaller against packaging/macos/yazses.spec → dist/YazSes.app
#   4. Wrap the .app in a .dmg with create-dmg.
#
# Outputs:
#   dist/YazSes-<VERSION>.dmg
#
# Requires:  macOS, Xcode command-line tools, Homebrew (for create-dmg).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "build-macos.sh requires macOS; got $(uname -s)" >&2
    exit 1
fi

VERSION="$(grep -E '^version = ' pyproject.toml | head -1 | sed -E 's/version = "(.+)"/\1/')"
echo "==> Building YazSes ${VERSION}"

if ! command -v uv >/dev/null 2>&1; then
    echo "uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi
if ! command -v create-dmg >/dev/null 2>&1; then
    echo "create-dmg not found. Install: brew install create-dmg" >&2
    exit 1
fi

echo "==> Syncing runtime dependencies"
uv sync

echo "==> Installing PyInstaller"
uv pip install 'pyinstaller>=6.10'

echo "==> Cleaning previous build"
rm -rf build dist

echo "==> Running PyInstaller"
uv run pyinstaller packaging/macos/yazses.spec --clean --noconfirm

if [[ ! -d dist/YazSes.app ]]; then
    echo "PyInstaller did not produce dist/YazSes.app" >&2
    exit 1
fi

echo "==> Building .dmg"
DMG="dist/YazSes-${VERSION}.dmg"
rm -f "${DMG}"
create-dmg \
    --volname "YazSes ${VERSION}" \
    --window-size 540 380 \
    --icon-size 96 \
    --app-drop-link 380 180 \
    --hide-extension "YazSes.app" \
    "${DMG}" \
    dist/YazSes.app

echo "==> Done: ${DMG}"
ls -lh "${DMG}"
