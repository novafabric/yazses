# PyInstaller spec file for YazSes (Windows).
#
# Produces a --onedir bundle at dist/YazSes/ that Inno Setup wraps into a
# self-contained installer. Single binary dispatches by argv (--tray | --daemon
# | --cli); Inno Setup adds shortcuts that pass the right flag.
#
# Usage (from repo root, on Windows):
#     uv run pyinstaller packaging/windows/yazses.spec --clean --noconfirm

# ruff: noqa
# mypy: ignore-errors

from __future__ import annotations

from pathlib import Path

REPO = Path(SPECPATH).resolve().parents[1]
ENTRY = str(REPO / "src" / "yazses" / "__main__.py")
ICON = REPO / "assets" / "yazses.ico"

block_cipher = None


a = Analysis(
    [ENTRY],
    pathex=[str(REPO / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[
        # pywin32 sub-modules used by the named-pipe IPC.
        "win32pipe",
        "win32file",
        "pywintypes",
        "winreg",
        # pystray + Pillow loads its assets dynamically.
        "pystray",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        # faster-whisper / ctranslate2 native bridge.
        "faster_whisper",
        "ctranslate2",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "evdev",
        "yazses.platform.linux",
        "yazses.platform.macos",
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
    icon=str(ICON) if ICON.exists() else None,
    version_file=None,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
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
