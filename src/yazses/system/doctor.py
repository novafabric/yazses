"""`yazses doctor` — diagnostics for the active platform.

Permission checks delegate to platform.permissions. Linux-specific extras
(X11/Wayland session, injection tool availability) remain inline here for now;
when Mac and Windows ship they grow their own extras blocks.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from yazses.platform import PermissionState, get_platform

# (name, status, detail) — status is "OK" | "FAIL" | "SKIP" | "WARN"
_Check = tuple[str, str, str]


def _tool(label: str, *, required: bool) -> _Check:
    found = bool(shutil.which(label))
    if found:
        return (f"  {label}", "OK", "found")
    if required:
        return (f"  {label}", "FAIL", "not installed")
    return (f"  {label}", "SKIP", "not needed on this session type")


def run_doctor() -> None:
    platform = get_platform()
    perms = platform.permissions
    paths = platform.paths

    checks: list[_Check] = []

    checks.append(("Platform", "OK", platform.name))

    # Keyboard capture
    kb = perms.check_keyboard_capture()
    checks.append((
        "Keyboard capture",
        "OK" if kb is PermissionState.OK else "FAIL",
        kb.value if kb is PermissionState.OK else f"{kb.value} — {perms.how_to_grant()}",
    ))

    # Microphone
    mic = perms.check_microphone()
    checks.append((
        "Microphone",
        "OK" if mic in (PermissionState.OK, PermissionState.NOT_APPLICABLE) else "FAIL",
        mic.value,
    ))

    # Linux-specific injection tools
    if sys.platform == "linux":
        is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        is_x11 = bool(os.environ.get("DISPLAY"))
        session = "Wayland" if is_wayland else ("X11" if is_x11 else "unknown")
        session_ok = is_wayland or is_x11
        checks.append(("Session type", "OK" if session_ok else "WARN", session))

        # X11 tools: required on X11, skip on Wayland
        checks.append(_tool("xdotool", required=is_x11 or not is_wayland))
        checks.append(_tool("ydotool", required=is_wayland))
        checks.append(_tool("wtype",   required=is_wayland))
        checks.append(_tool("xclip",   required=is_x11 or not is_wayland))
        checks.append(_tool("wl-copy", required=is_wayland))

    # Model cache (Hugging Face)
    hf_cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    checks.append(("Model cache", "OK" if hf_cache.exists() else "WARN", str(hf_cache)))

    # Config dir — create it if absent (first-run scenario)
    if paths.config_dir.exists():
        checks.append(("Config dir", "OK", str(paths.config_dir)))
    else:
        try:
            paths.config_dir.mkdir(parents=True, exist_ok=True)
            checks.append(("Config dir", "OK", f"{paths.config_dir} (created)"))
        except OSError as exc:
            checks.append(("Config dir", "FAIL", f"could not create: {exc}"))

    # EMG serial port (when configured)
    try:
        from yazses.config import load_config
        cfg = load_config(paths.config_file if paths.config_file.exists() else None)
        if cfg.emg.device_port:
            port = Path(cfg.emg.device_port)
            checks.append((
                "EMG serial port",
                "OK" if port.exists() else "FAIL",
                f"{port} {'accessible' if port.exists() else 'not found'}",
            ))
        if cfg.emg.ble_address:
            checks.append(("EMG BLE address", "OK", cfg.emg.ble_address))
    except Exception:
        pass

    print(f"YazSes doctor ({platform.name}):")
    for name, status, detail in checks:
        print(f"  [{status}] {name}: {detail}")
