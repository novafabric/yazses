"""Registry and download utility for SLM intent-routing models (v0.4.1).

Models are GGUF files stored in the user's cache directory:
  Linux:   ~/.cache/yazses/models/
  macOS:   ~/Library/Caches/yazses/models/
  Windows: %LOCALAPPDATA%\\yazses\\models\\

Usage:
    from yazses.commands.model_manager import download_model, list_models
    path = download_model("qwen2.5-0.5b")
"""
from __future__ import annotations

import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import platformdirs

log = logging.getLogger(__name__)

_CACHE_BASE = Path(platformdirs.user_cache_dir("yazses")) / "models"


@dataclass(frozen=True)
class ModelInfo:
    id: str
    filename: str
    url: str
    size_mb: int
    description: str


REGISTRY: dict[str, ModelInfo] = {
    "qwen2.5-0.5b": ModelInfo(
        id="qwen2.5-0.5b",
        filename="qwen2.5-0.5b-instruct-q4_k_m.gguf",
        url=(
            "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF"
            "/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"
        ),
        size_mb=397,
        description="Qwen2.5 0.5B — fast intent classifier, recommended for Tier 2 routing",
    ),
    "phi3-mini": ModelInfo(
        id="phi3-mini",
        filename="Phi-3-mini-4k-instruct-q4.gguf",
        url=(
            "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf"
            "/resolve/main/Phi-3-mini-4k-instruct-q4.gguf"
        ),
        size_mb=2200,
        description="Phi-3 mini — higher accuracy, ~300 ms per query",
    ),
}


def models_dir() -> Path:
    _CACHE_BASE.mkdir(parents=True, exist_ok=True)
    return _CACHE_BASE


def list_models() -> list[ModelInfo]:
    return list(REGISTRY.values())


def local_path(model_id: str) -> Path | None:
    """Return the local path if the model is already downloaded, else None."""
    info = REGISTRY.get(model_id)
    if info is None:
        return None
    p = models_dir() / info.filename
    return p if p.exists() else None


def download_model(model_id: str, *, show_progress: bool = True) -> Path:
    """Download *model_id* to the local cache and return the path.

    Skips the download if the file already exists. Raises ValueError for
    unknown model IDs and re-raises urllib errors on network failure.
    Partial files are removed on failure.
    """
    info = REGISTRY.get(model_id)
    if info is None:
        known = ", ".join(REGISTRY)
        raise ValueError(f"Unknown model {model_id!r}. Known models: {known}")

    dest = models_dir() / info.filename
    if dest.exists():
        log.info("Model %s already present at %s", model_id, dest)
        return dest

    log.info("Downloading %s (%d MB) from %s", model_id, info.size_mb, info.url)

    def _progress(block: int, block_size: int, total: int) -> None:
        if not show_progress or total <= 0:
            return
        done = min(block * block_size, total)
        pct = 100 * done // total
        filled = pct // 2
        bar = "#" * filled + " " * (50 - filled)
        print(f"\r  [{bar}] {pct:3d}%", end="", flush=True)

    if show_progress:
        print(f"Downloading {info.id} ({info.size_mb} MB)…")

    try:
        urllib.request.urlretrieve(info.url, dest, reporthook=_progress)
    except Exception:
        dest.unlink(missing_ok=True)
        raise

    if show_progress:
        print(f"\r  [{'#' * 50}] 100%")
        print(f"Saved to {dest}")

    return dest
