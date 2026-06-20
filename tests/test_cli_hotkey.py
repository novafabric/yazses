"""CLI status messages show the *configured* hotkey, not the platform default.

`start`/`test` used to print `platform.default_hotkey` ("space"), which is wrong
whenever the user configured a different `[hotkey] key` (e.g. "right_alt") — the
daemon binds the configured key but the message said "space". `_resolved_hotkey`
reads the configured key, falling back to the platform default.
"""
from __future__ import annotations

import types
from pathlib import Path

from yazses import cli


def _fake_platform(config_file: Path, default="space"):
    return types.SimpleNamespace(
        default_hotkey=default,
        paths=types.SimpleNamespace(config_file=config_file),
    )


def test_resolved_hotkey_uses_configured_key(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[hotkey]\nkey = \"right_alt\"\n")
    assert cli._resolved_hotkey(_fake_platform(cfg)) == "right_alt"


def test_resolved_hotkey_falls_back_to_platform_default(tmp_path):
    missing = tmp_path / "absent.toml"
    assert cli._resolved_hotkey(_fake_platform(missing, default="space")) == "space"


# ---- dedicated command key -------------------------------------------------

def test_command_key_defaults_to_empty():
    from yazses.config import Config

    assert Config().hotkey.command_key == ""


def test_command_key_round_trips_through_config(tmp_path):
    from yazses.config import load_config
    from yazses.system.configedit import set_config_key

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[hotkey]\nkey = "right_alt"\n')
    set_config_key(cfg_file, "hotkey", "command_key", "right_ctrl")
    assert load_config(cfg_file).hotkey.command_key == "right_ctrl"
    # 'off' clears it
    set_config_key(cfg_file, "hotkey", "command_key", "")
    assert load_config(cfg_file).hotkey.command_key == ""
    # the dictation key was never disturbed
    assert load_config(cfg_file).hotkey.key == "right_alt"
