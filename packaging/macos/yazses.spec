# PyInstaller spec file for YazSes (macOS).
#
# Builds a single-binary, single-bundle .app from src/yazses/__main__.py.
# The binary dispatches by argv: --tray (default) | --daemon | --cli.
#
# Usage (from repo root):
#     uv run pyinstaller packaging/macos/yazses.spec --clean --noconfirm
#
# Outputs:
#     dist/YazSes.app

# ruff: noqa
# mypy: ignore-errors

from __future__ import annotations

from pathlib import Path

REPO = Path(SPECPATH).resolve().parents[1]
ENTRY = str(REPO / "src" / "yazses" / "__main__.py")
ICON = REPO / "assets" / "yazses.icns"

block_cipher = None


a = Analysis(
    [ENTRY],
    pathex=[str(REPO / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[
        # PyObjC sub-modules that PyInstaller's static analysis sometimes misses.
        "Quartz",
        "AppKit",
        "Foundation",
        "ApplicationServices",
        "CoreFoundation",
        "AVFoundation",
        # rumps loads its assets dynamically.
        "rumps",
        # faster-whisper / ctranslate2 native bridge.
        "faster_whisper",
        "ctranslate2",
        # Linux backends are skipped on darwin via env markers, but PyInstaller
        # may still try to import them; suppress by keeping the list mac-only.
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "evdev",
        "yazses.platform.linux",
        "yazses.platform.windows",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="YazSes",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,         # --windowed
    disable_windowed_traceback=False,
    target_arch=None,      # universal2 in CI; fallback to host arch locally
    codesign_identity=None,  # signed in a separate step (deferred to public beta)
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="YazSes",
)

app = BUNDLE(
    coll,
    name="YazSes.app",
    icon=str(ICON) if ICON.exists() else None,
    bundle_identifier="com.yazses.app",
    info_plist={
        # Identity
        "CFBundleName": "YazSes",
        "CFBundleDisplayName": "YazSes",
        "CFBundleIdentifier": "com.yazses.app",
        "CFBundleVersion": "0.1.2",
        "CFBundleShortVersionString": "0.1.2",
        "CFBundleExecutable": "YazSes",

        # No Dock icon — tray-only app.
        "LSUIElement": True,

        # Minimum macOS supporting PyObjC 11 + Apple Silicon.
        "LSMinimumSystemVersion": "11.0",

        # Permission prompt strings. Without these the OS rejects access without
        # showing a prompt to the user.
        "NSMicrophoneUsageDescription":
            "YazSes transcribes speech locally; the microphone is used "
            "only while you hold the dictation key.",
        "NSAppleEventsUsageDescription":
            "YazSes does not send Apple Events; this entitlement is "
            "present for compatibility with macOS Accessibility prompts.",

        # High-resolution display support.
        "NSHighResolutionCapable": True,
    },
)
