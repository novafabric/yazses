"""Futuristic on-screen voice-activity overlay.

A standalone process (``yazses-overlay``) that draws an animated "sonar" — neon
rings that expand near the cursor and pulse with your live mic level while you
dictate. It is a thin IPC client that polls the daemon's ``status`` RPC, so
either the Python or the Rust daemon can drive it.

The package is split into pure-logic modules (``envelope``, ``animation``,
``position``, ``poller``) that have no GUI dependency and are fully unit-tested,
and a thin Qt rendering layer (``widget``, ``app``) that imports PySide6 lazily.
Importing this package never imports PySide6.
"""
