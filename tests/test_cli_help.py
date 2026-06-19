"""CLI usability: `-h` everywhere, examples in help, grouped panels, completion.

Covers the user-facing help/UX contract so it can't silently regress:
a single `-h` works on the app and on every command/group, each key command
shows an example, the top-level help advertises shell completion, and commands
are organised into rich help panels.
"""
from __future__ import annotations

from typer.testing import CliRunner

import yazses.cli as cli

runner = CliRunner()
# Force a wide terminal so rich does not wrap help text mid-phrase, keeping
# substring assertions stable across environments.
WIDE = {"COLUMNS": "220", "TERM": "dumb"}


def _help(args):
    return runner.invoke(cli.app, args, env=WIDE)


# ---- `-h` works everywhere -------------------------------------------------

def test_dash_h_top_level():
    r = _help(["-h"])
    assert r.exit_code == 0
    assert "Usage" in r.output


def test_dash_h_on_a_command():
    r = _help(["start", "-h"])
    assert r.exit_code == 0
    assert "Usage" in r.output


def test_dash_h_on_a_group():
    assert _help(["model", "-h"]).exit_code == 0
    assert _help(["corpus", "-h"]).exit_code == 0


def test_dash_h_on_a_group_subcommand():
    r = _help(["corpus", "status", "-h"])
    assert r.exit_code == 0
    assert "Usage" in r.output


def test_double_dash_help_still_works():
    assert _help(["--help"]).exit_code == 0


# ---- examples, completion, panels -----------------------------------------

def test_top_level_help_lists_examples():
    out = _help(["--help"]).output
    assert "Examples" in out


def test_top_level_help_advertises_completion():
    out = _help(["--help"]).output
    assert "completion" in out.lower()


def test_command_help_shows_a_concrete_example():
    out = _help(["mic-level", "-h"]).output
    assert "Example" in out          # epilog heading, not just the Usage line
    assert "--set" in out


def test_punch_in_help_shows_a_concrete_example():
    out = _help(["punch-in", "-h"]).output
    assert "Example" in out
    assert "--dry-run" in out


def test_help_groups_commands_into_panels():
    out = _help(["--help"]).output
    assert "Daemon" in out  # a rich_help_panel section title


# ---- version flag: long + short -------------------------------------------

def _looks_like_version(out: str) -> bool:
    import re

    return bool(re.search(r"yazses\s+\d+\.\d+", out))


def test_version_long_flag():
    r = runner.invoke(cli.app, ["--version"], env=WIDE)
    assert r.exit_code == 0
    assert _looks_like_version(r.output)


def test_version_short_flag():
    r = runner.invoke(cli.app, ["-V"], env=WIDE)
    assert r.exit_code == 0
    assert _looks_like_version(r.output)


# ---- bare invocation is friendly (shows help, not a bare error) -----------

def test_bare_invocation_shows_help():
    r = runner.invoke(cli.app, [], env=WIDE)
    assert "Usage" in r.output
