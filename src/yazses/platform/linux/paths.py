"""XDG-style paths for Linux, via platformdirs."""

from __future__ import annotations

from pathlib import Path

from platformdirs import PlatformDirs

from yazses.platform.base import Paths

_APP = "yazses"


def build_paths() -> Paths:
    dirs = PlatformDirs(appname=_APP, appauthor=False, ensure_exists=False)
    state_dir = Path(dirs.user_runtime_dir or dirs.user_state_dir)
    return Paths(
        config_dir=Path(dirs.user_config_dir),
        state_dir=state_dir,
        cache_dir=Path(dirs.user_cache_dir),
        log_dir=Path(dirs.user_log_dir),
        data_dir=Path(dirs.user_data_dir),
    )
