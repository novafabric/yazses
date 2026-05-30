"""Platform detection — picks the right concrete backend bundle."""

from __future__ import annotations

import sys
from functools import lru_cache

from yazses.platform.base import Platform, UnsupportedPlatformError


@lru_cache(maxsize=1)
def get_platform() -> Platform:
    if sys.platform == "linux":
        from yazses.platform.linux import build_platform
        return build_platform()
    if sys.platform == "darwin":
        from yazses.platform.macos import build_platform  # noqa: F401  (Phase 1)
        return build_platform()
    if sys.platform == "win32":
        from yazses.platform.windows import build_platform  # noqa: F401  (Phase 2)
        return build_platform()
    raise UnsupportedPlatformError(
        f"YazSes has no backend for sys.platform={sys.platform!r}. "
        "Supported: linux, darwin, win32."
    )


def reset_platform_cache() -> None:
    """Drop the cached Platform — useful in tests that swap sys.platform."""
    get_platform.cache_clear()
