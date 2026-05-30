"""macOS paths — ~/Library/{Application Support,Caches,Logs}/yazses."""

from __future__ import annotations

from pathlib import Path

from platformdirs import PlatformDirs

from yazses.platform.base import Paths

_APP = "yazses"


def build_paths() -> Paths:
    dirs = PlatformDirs(appname=_APP, appauthor=False, ensure_exists=False)
    config_dir = Path(dirs.user_config_dir)
    return Paths(
        config_dir=config_dir,
        # macOS has no XDG_RUNTIME_DIR; reuse the config dir for sockets/PID.
        # The full sun_path stays well under macOS's 104-byte limit.
        state_dir=config_dir,
        cache_dir=Path(dirs.user_cache_dir),
        log_dir=Path(dirs.user_log_dir),
        data_dir=Path(dirs.user_data_dir),
    )
