"""Section-aware TOML key setter (backs `yazses hotkey set`, etc.)."""
from __future__ import annotations

from yazses.system.configedit import set_config_key


def test_creates_file_when_missing(tmp_path):
    p = tmp_path / "config.toml"
    set_config_key(p, "hotkey", "key", "right_ctrl")
    assert p.read_text() == '[hotkey]\nkey = "right_ctrl"\n'


def test_replaces_existing_key_in_section(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[hotkey]\n# a comment\nkey = "right_alt"\n\n[stt]\nmodel = "small.en"\n')
    set_config_key(p, "hotkey", "key", "space")
    t = p.read_text()
    assert 'key = "space"' in t
    assert 'key = "right_alt"' not in t
    assert "# a comment" in t              # comments preserved
    assert 'model = "small.en"' in t       # other sections untouched


def test_inserts_key_when_section_exists_without_it(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[hotkey]\nhold_threshold_ms = 500\n')
    set_config_key(p, "hotkey", "key", "left_alt")
    t = p.read_text()
    assert 'key = "left_alt"' in t
    assert "hold_threshold_ms = 500" in t


def test_appends_section_when_missing(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[stt]\nmodel = "small.en"\n')
    set_config_key(p, "hotkey", "key", "right_shift")
    t = p.read_text()
    assert "[hotkey]" in t
    assert 'key = "right_shift"' in t
    assert 'model = "small.en"' in t


def test_does_not_touch_same_key_name_in_other_section(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[other]\nkey = "keep-me"\n\n[hotkey]\nkey = "right_alt"\n')
    set_config_key(p, "hotkey", "key", "space")
    t = p.read_text()
    assert 'key = "keep-me"' in t          # [other].key untouched
    assert 'key = "space"' in t


def test_unquoted_value(tmp_path):
    p = tmp_path / "config.toml"
    set_config_key(p, "hotkey", "hold_threshold_ms", 700, quote=False)
    assert "hold_threshold_ms = 700" in p.read_text()
