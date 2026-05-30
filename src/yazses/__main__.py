"""Mode-dispatched entry point for a single PyInstaller binary.

Bundled binaries on macOS / Windows ship as a single executable so the .app /
.exe can run as the tray (default), the daemon, or the CLI depending on argv.
Pip-installed users keep using the dedicated console scripts (``yazses``,
``yazses-daemon``, ``yazses-tray``).

Modes:
- ``--daemon``  → run the dictation daemon
- ``--tray``    → run the tray application (also the default if no args)
- ``--cli``     → run the Typer CLI; remaining args pass through to it
"""

from __future__ import annotations

import sys


def main() -> None:
    args = sys.argv[1:]
    mode = args[0] if args else "--tray"

    if mode == "--daemon":
        from yazses.main import run as run_daemon

        sys.argv = [sys.argv[0]] + args[1:]
        run_daemon()
    elif mode == "--tray":
        from yazses.tray.app import run as run_tray

        sys.argv = [sys.argv[0]] + args[1:]
        run_tray()
    elif mode == "--cli":
        from yazses.cli import app

        sys.argv = [sys.argv[0]] + args[1:]
        app()
    else:
        # No mode flag → default to CLI (matches the pip-installed `yazses` script).
        from yazses.cli import app

        app()


if __name__ == "__main__":
    main()
