"""`yazses doctor` — diagnostics for the active platform.

Permission checks delegate to platform.permissions. Linux-specific extras
(X11/Wayland session, injection tool availability) remain inline here for now;
when Mac and Windows ship they grow their own extras blocks.
"""

from __future__ import annotations

import os
import shutil
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from yazses.platform import PermissionState, get_platform
from yazses.system.miclevel import LevelStats

# (name, status, detail) — status is "OK" | "FAIL" | "SKIP" | "WARN"
_Check = tuple[str, str, str]


def _tool(label: str, *, required: bool) -> _Check:
    found = bool(shutil.which(label))
    if found:
        return (f"  {label}", "OK", "found")
    if required:
        return (f"  {label}", "FAIL", "not installed")
    return (f"  {label}", "SKIP", "not needed on this session type")


# Wayland compositors where `wtype` is blocked (no virtual-keyboard protocol),
# so keystroke injection requires ydotool + a running ydotoold.
_UINPUT_ONLY_DESKTOPS = ("gnome", "kde", "plasma", "cinnamon", "unity", "mate", "xfce", "lxqt")


def _injection_readiness(is_wayland: bool, is_x11: bool) -> list[_Check]:
    """Report whether keystroke injection will actually work, with the fix."""
    from yazses.inject.auto import ydotool_ready, ydotool_socket_path

    out: list[_Check] = []
    if is_wayland:
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        gnome_like = any(d in desktop for d in _UINPUT_ONLY_DESKTOPS)
        sock = ydotool_socket_path()
        if ydotool_ready():
            out.append(("ydotoold", "OK", f"running ({sock})"))
            out.append(("Injection", "OK", "ydotool — works on any Wayland compositor"))
        elif shutil.which("ydotool"):
            out.append(("ydotoold", "FAIL" if gnome_like else "WARN",
                        f"not running (no socket at {sock}) — run `yazses setup`"))
            if gnome_like:
                out.append(("Injection", "FAIL",
                            "GNOME/KDE Wayland needs ydotool+ydotoold (wtype is blocked) — run `yazses setup`"))
            elif shutil.which("wtype"):
                out.append(("Injection", "OK", "wtype — ydotoold off but fine on wlroots compositors"))
            else:
                out.append(("Injection", "FAIL", "no working backend — run `yazses setup`"))
        elif shutil.which("wtype"):
            if gnome_like:
                out.append(("Injection", "FAIL",
                            "wtype does not work on GNOME/KDE Wayland — run `yazses setup` (installs ydotool+ydotoold)"))
            else:
                out.append(("Injection", "OK", "wtype (wlroots)"))
        else:
            out.append(("Injection", "FAIL", "no Wayland injector installed — run `yazses setup`"))
    elif is_x11:
        if shutil.which("xdotool"):
            out.append(("Injection", "OK", "xdotool (X11)"))
        elif shutil.which("xclip"):
            out.append(("Injection", "WARN", "clipboard paste only (install xdotool for direct typing)"))
        else:
            out.append(("Injection", "FAIL", "no X11 injector — run `yazses setup`"))
    return out


def _prosody_check(enabled: bool) -> _Check | None:
    """Report whether the optional ``prosody`` extra (parselmouth) is importable.

    Only runs when ``[prosody] enabled`` (spec-prosody-ink). Absent is a WARN, not
    a FAIL: pause→paragraph still works with no dep; only emphasis→bold needs
    parselmouth and degrades to pause-only when it is missing.
    """
    if not enabled:
        return None
    try:
        import parselmouth  # type: ignore  # noqa: F401
    except Exception:
        return (
            "prosody extra (parselmouth)",
            "WARN",
            "not installed — emphasis disabled, pause→¶ still works "
            "(uv sync --extra prosody)",
        )
    return ("prosody extra (parselmouth)", "OK", "importable")


def _extra_check(label: str, enabled: bool, module: str, hint: str) -> _Check | None:
    """Generic optional-extra importability check (None when the feature is off)."""
    if not enabled:
        return None
    try:
        __import__(module)
    except Exception:
        return (label, "WARN", f"not installed — feature dormant ({hint})")
    return (label, "OK", "importable")


def _dysfluency_check(enabled: bool) -> _Check | None:
    """Report Dysfluency-Friendly Mode status (ADR-015). Skipped when off."""
    if not enabled:
        return None
    return (
        "Dysfluency-friendly mode",
        "OK",
        "on — collapsing repetitions/prolongations, wider onset padding",
    )


def _version_check() -> _Check:
    """Report the installed YazSes version (one-stop health check)."""
    try:
        return ("Version", "OK", f"yazses {_pkg_version('yazses')}")
    except PackageNotFoundError:
        return ("Version", "WARN", "yazses version metadata not found")


def _daemon_check(platform) -> _Check:
    """Report whether the daemon is running, with live state when IPC answers."""
    lifecycle = platform.lifecycle
    if not lifecycle.is_running():
        return ("Daemon", "WARN", "not running — start with `yazses start`")
    pid = lifecycle.read_pid()
    try:
        client = platform.ipc_client_factory(platform.paths.ipc_socket)
        info = client.call("status")
        bits = [b for b in (
            f"state {info.get('state')}" if info.get("state") else "",
            f"model {info.get('model')}" if info.get("model") else "",
        ) if b]
        suffix = (", " + ", ".join(bits)) if bits else ""
        return ("Daemon", "OK", f"running (PID {pid}{suffix})")
    except Exception:
        # Running but IPC not yet ready (still loading the model) or unreachable.
        return ("Daemon", "OK", f"running (PID {pid}; IPC not ready)")


def _model_check(model: str, hf_cache: Path) -> _Check:
    """Report whether the configured STT model is available locally.

    A local directory/file path is checked directly; otherwise we scan the
    Hugging Face hub cache for a ``models--…<model>`` snapshot. We match on the
    cache directory name (no ``faster_whisper`` import) so doctor stays fast.
    """
    local = Path(model).expanduser()
    if local.exists():
        return ("STT model", "OK", f"{model} (local files)")
    token = model.split("/")[-1]
    if hf_cache.exists():
        for entry in hf_cache.iterdir():
            if (
                entry.name.startswith("models--")
                and entry.name.endswith(token)
                and (entry / "snapshots").exists()
            ):
                return ("STT model", "OK", f"{model} (cached)")
    return (
        "STT model",
        "WARN",
        f"{model} not downloaded — fetched automatically on first dictation "
        "(needs network once)",
    )


def _config_summary(cfg, config_file: Path) -> list[_Check]:
    """Surface the active config file, resolved hotkey, and STT prompt status."""
    out: list[_Check] = []
    if config_file.exists():
        out.append(("Config file", "OK", str(config_file)))
    else:
        out.append((
            "Config file", "WARN",
            f"{config_file} (absent — using built-in defaults)",
        ))
    out.append((
        "Hotkey", "OK",
        f"{cfg.hotkey.key} (hold {cfg.hotkey.hold_threshold_ms} ms)",
    ))
    prompt = (cfg.stt.initial_prompt or "").strip()
    if prompt:
        preview = prompt if len(prompt) <= 40 else prompt[:37] + "..."
        out.append(("STT prompt", "OK", f"primed: {preview!r}"))
    else:
        out.append((
            "STT prompt", "OK",
            "app name only (set [stt] initial_prompt to add vocabulary)",
        ))
    return out


def _sample_mic(cfg, seconds: float) -> LevelStats:
    """Record a short ambient clip and return its level stats (seam for tests)."""
    from yazses.system.miclevel import analyze, record

    sr = cfg.audio.sample_rate
    return analyze(record(seconds, sr), sr)


def _mic_level_check(cfg, seconds: float = 2.0) -> _Check:
    """Passive ambient level vs the VAD gate (no speech needed).

    Warns when the resting room level already meets/exceeds ``vad_threshold`` —
    the gate would then pass noise through as spurious transcripts. A quiet room
    is OK; for speech-level calibration the detail points at ``yazses mic-level``.
    """
    try:
        stats = _sample_mic(cfg, seconds)
    except Exception as exc:
        return ("Mic level", "WARN", f"could not sample microphone ({exc})")
    thr = cfg.accessibility.vad_threshold
    if not stats.is_silent and stats.mean_abs >= thr:
        return (
            "Mic level", "WARN",
            f"ambient {stats.mean_abs:.4f} >= vad_threshold {thr} — room noise may "
            "trigger spurious transcripts; raise it or run `yazses mic-level`",
        )
    return (
        "Mic level", "OK",
        f"ambient {stats.mean_abs:.4f} under vad_threshold {thr} "
        "(speak-test with `yazses mic-level`)",
    )


def run_doctor(check_mic: bool = False, mic_seconds: float = 2.0) -> None:
    platform = get_platform()
    perms = platform.permissions
    paths = platform.paths

    # Load config once up front so the version/daemon/model/config checks can use
    # it; a malformed config degrades to defaults rather than crashing doctor.
    cfg = None
    try:
        from yazses.config import load_config
        # load_config returns defaults when the path is absent; pass it directly
        # rather than None (None falls back to the default user config path).
        cfg = load_config(paths.config_file)
    except Exception:
        cfg = None

    checks: list[_Check] = []

    checks.append(("Platform", "OK", platform.name))
    checks.append(_version_check())
    checks.append(_daemon_check(platform))

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

    # Opt-in passive mic-level vs VAD threshold (records a short ambient clip).
    if check_mic and cfg is not None:
        checks.append(_mic_level_check(cfg, mic_seconds))

    # Linux-specific injection tools
    if sys.platform == "linux":
        is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        is_x11 = bool(os.environ.get("DISPLAY"))
        session = "Wayland" if is_wayland else ("X11" if is_x11 else "unknown")
        session_ok = is_wayland or is_x11
        checks.append(("Session type", "OK" if session_ok else "WARN", session))

        # Injection backends are informational (only one is needed per session);
        # the actual pass/fail signal is the "Injection" readiness check below.
        checks.append(_tool("xdotool", required=False))
        checks.append(_tool("ydotool", required=False))
        checks.append(_tool("wtype",   required=False))
        checks.append(_tool("xclip",   required=False))
        checks.append(_tool("wl-copy", required=False))

        checks.extend(_injection_readiness(is_wayland, is_x11))

    # Model cache (Hugging Face)
    hf_cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    checks.append(("Model cache", "OK" if hf_cache.exists() else "WARN", str(hf_cache)))

    # Configured STT model availability (downloaded vs fetched-on-first-use).
    if cfg is not None:
        checks.append(_model_check(cfg.stt.model, hf_cache))

    # Config dir — create it if absent (first-run scenario)
    if paths.config_dir.exists():
        checks.append(("Config dir", "OK", str(paths.config_dir)))
    else:
        try:
            paths.config_dir.mkdir(parents=True, exist_ok=True)
            checks.append(("Config dir", "OK", f"{paths.config_dir} (created)"))
        except OSError as exc:
            checks.append(("Config dir", "FAIL", f"could not create: {exc}"))

    # Active config file, hotkey, and STT prompt summary.
    if cfg is not None:
        checks.extend(_config_summary(cfg, paths.config_file))

    # EMG serial port (when configured)
    try:
        if cfg is None:
            raise RuntimeError("config unavailable")
        if cfg.emg.device_port:
            port = Path(cfg.emg.device_port)
            checks.append((
                "EMG serial port",
                "OK" if port.exists() else "FAIL",
                f"{port} {'accessible' if port.exists() else 'not found'}",
            ))
        if cfg.emg.ble_address:
            checks.append(("EMG BLE address", "OK", cfg.emg.ble_address))
        prosody = _prosody_check(cfg.prosody.enabled)
        if prosody is not None:
            checks.append(prosody)
        dysfluency = _dysfluency_check(cfg.accessibility.dysfluency_friendly)
        if dysfluency is not None:
            checks.append(dysfluency)
        # v2 cognitive-layer extras (report only when the feature is enabled).
        for chk in (
            _extra_check("tts extra (kokoro-onnx)", cfg.tts.enabled,
                         "kokoro_onnx", "uv sync --extra tts"),
            _extra_check("voiceprint extra (speechbrain)",
                         cfg.voiceprint.enabled or cfg.cocktail.enabled,
                         "speechbrain", "uv sync --extra voiceprint"),
            _extra_check("gaze extra (l2cs)", cfg.gaze.enabled,
                         "l2cs", "pip install l2cs mediapipe opencv-python"),
        ):
            if chk is not None:
                checks.append(chk)
    except Exception:
        pass

    print(f"YazSes doctor ({platform.name}):")
    for name, status, detail in checks:
        print(f"  [{status}] {name}: {detail}")
