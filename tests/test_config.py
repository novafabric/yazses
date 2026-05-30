import tomllib
from pathlib import Path
import pytest
from yazses.config import Config, SttConfig, HotkeyConfig, AudioConfig, InjectionConfig, GeneralConfig, load_config


def test_defaults():
    cfg = Config()
    assert cfg.stt.model == "base.en"
    assert cfg.stt.device == "cpu"
    assert cfg.stt.compute_type == "int8"
    assert cfg.streaming.enabled is False    # batch transcribe-on-release by default
    assert cfg.hotkey.hold_threshold_ms == 500
    assert cfg.audio.sample_rate == 16000
    assert cfg.audio.channels == 1
    assert cfg.audio.max_record_seconds == 90
    assert cfg.injection.backend == "auto"
    assert cfg.injection.fallback_to_clipboard is True
    assert cfg.general.log_level == "INFO"


def test_load_config_missing_file_returns_defaults(tmp_path):
    cfg = load_config(tmp_path / "nonexistent.toml")
    assert cfg.stt.model == "base.en"


def test_load_config_partial_override(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[stt]\nmodel = "small.en"\n')
    cfg = load_config(config_file)
    assert cfg.stt.model == "small.en"
    assert cfg.stt.device == "cpu"          # default preserved


def test_load_config_full_section(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[hotkey]\nhold_threshold_ms = 800\n'
        '[audio]\nmax_record_seconds = 30\n'
    )
    cfg = load_config(config_file)
    assert cfg.hotkey.hold_threshold_ms == 800
    assert cfg.audio.max_record_seconds == 30
    assert cfg.stt.model == "base.en"       # unrelated section defaults preserved


def test_overlay_defaults():
    cfg = Config()
    assert cfg.overlay.enabled is False     # opt-in; off by default
    assert cfg.overlay.style == "sonar"
    assert cfg.overlay.position == "cursor"
    assert cfg.overlay.react_to_voice is True
    assert cfg.overlay.accent == "#00e5ff"
    assert cfg.overlay.size_px == 220
    assert cfg.overlay.fps == 60
    assert cfg.overlay.cursor_offset_px == 28


def test_overlay_section_override(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[overlay]\n'
        'enabled = true\n'
        'position = "bottom_center"\n'
        'accent = "#ff00aa"\n'
        'fps = 30\n'
    )
    cfg = load_config(config_file)
    assert cfg.overlay.enabled is True
    assert cfg.overlay.position == "bottom_center"
    assert cfg.overlay.accent == "#ff00aa"
    assert cfg.overlay.fps == 30
    assert cfg.overlay.react_to_voice is True   # default preserved
