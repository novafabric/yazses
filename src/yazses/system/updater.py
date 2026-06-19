"""Self-update for `yazses update` — check the matching source, upgrade if newer.

YazSes can be installed several ways (snap, `uv tool`, pipx, plain pip). This
module detects which one the running interpreter came from, looks up the latest
version from the source that matches (the tracked snap channel for snap, PyPI for
the pip-family installs), and only reports an update when it is *strictly* newer
than the running version — it never offers a downgrade.

Network (PyPI) and subprocess (snap/upgrade) are isolated behind small helpers so
the decision logic stays pure and testable offline.
"""
from __future__ import annotations

import json
import subprocess
import urllib.request
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version


@dataclass
class UpdateStatus:
    method: str                       # snap | uv | pipx | pip | unknown
    current: str
    latest: str | None
    available: bool
    command: list[str] | None         # the upgrade command to run (None if N/A)
    note: str = ""


# ---- install-method detection ----------------------------------------------

def detect_install_method(package_file: str | None = None) -> str:
    """Infer how YazSes was installed from the package's on-disk location.

    ``package_file`` defaults to this package's ``__file__``; pass an explicit
    path in tests. Returns ``snap`` | ``uv`` | ``pipx`` | ``pip``.
    """
    path = package_file if package_file is not None else __file__
    p = path.replace("\\", "/")
    if "/snap/" in p:
        return "snap"
    if "/uv/tools/" in p:
        return "uv"
    if "/pipx/" in p:
        return "pipx"
    return "pip"


# ---- version comparison ----------------------------------------------------

def is_newer(latest: str, current: str) -> bool:
    """True iff ``latest`` is a strictly newer version than ``current``.

    Returns False (never offer an update) if either string is not a valid
    version, so a parse failure can't trigger a spurious or downgrade upgrade.
    """
    try:
        return Version(latest) > Version(current)
    except (InvalidVersion, TypeError):
        return False


# ---- source parsers (pure) -------------------------------------------------

def _pypi_version_from_json(payload: dict) -> str | None:
    try:
        return payload["info"]["version"]
    except (KeyError, TypeError):
        return None


def _snap_tracked_version(info_text: str) -> str | None:
    """Parse `snap info` output for the version on the *tracked* channel.

    Falls back to None when the tracked channel shows ``--`` (no release).
    """
    tracked = None
    for line in info_text.splitlines():
        s = line.strip()
        if s.startswith("tracking:"):
            tracked = s.split(":", 1)[1].strip()
            break
    if not tracked:
        return None
    # Channel rows look like "  latest/edge:  0.5.1 2026-05-31 (11) 136MB -".
    prefix = tracked + ":"
    for line in info_text.splitlines():
        s = line.strip()
        if s.startswith(prefix):
            rest = s[len(prefix):].strip()
            token = rest.split()[0] if rest else "--"
            return None if token in ("--", "") else token
    return None


# ---- source lookups (network / subprocess) ---------------------------------

def latest_pypi_version(package: str = "yazses", *, timeout: float = 5.0) -> str | None:
    """Latest released version from PyPI's JSON API, or None on any failure."""
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (https only)
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    return _pypi_version_from_json(payload)


def latest_snap_version(name: str = "yazses", *, timeout: float = 10.0) -> str | None:
    """Latest version on the tracked snap channel via `snap info`, or None."""
    try:
        out = subprocess.run(
            ["snap", "info", name],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return _snap_tracked_version(out.stdout)


def _latest_for_method(method: str, package: str) -> str | None:
    """Resolve the latest version from the source matching the install method."""
    if method == "snap":
        return latest_snap_version(package)
    return latest_pypi_version(package)


# ---- upgrade command -------------------------------------------------------

def upgrade_command(method: str, package: str = "yazses") -> list[str] | None:
    """The shell command that upgrades a `method`-style install (None if unknown)."""
    if method == "snap":
        return ["sudo", "snap", "refresh", package]
    if method == "uv":
        return ["uv", "tool", "upgrade", package]
    if method == "pipx":
        return ["pipx", "upgrade", package]
    if method == "pip":
        return ["pip", "install", "--upgrade", package]
    return None


# ---- orchestration ---------------------------------------------------------

def check_update(
    current: str,
    *,
    method: str | None = None,
    package: str = "yazses",
) -> UpdateStatus:
    """Resolve the install method, find the latest version, decide if newer."""
    method = method or detect_install_method()
    latest = _latest_for_method(method, package)
    if latest is None:
        return UpdateStatus(
            method=method, current=current, latest=None, available=False,
            command=None, note="could not determine the latest version",
        )
    available = is_newer(latest, current)
    return UpdateStatus(
        method=method,
        current=current,
        latest=latest,
        available=available,
        command=upgrade_command(method, package) if available else None,
        note="",
    )


def run_upgrade(status: UpdateStatus) -> int:
    """Run the upgrade command for *status*; return its exit code (1 if none)."""
    if not status.command:
        return 1
    try:
        return subprocess.run(status.command, check=False).returncode
    except (OSError, subprocess.SubprocessError):
        return 1
