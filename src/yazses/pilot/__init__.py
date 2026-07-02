"""AT-SPI Voice Pilot — accessibility-tree desktop control (ADR-v2-007).

Voice-drive the desktop via the accessibility tree ("click Save", "focus the
terminal", "toggle dark mode") — element labels + roles + actions only, never a
screenshot (honours ADR-011). This package's ``plan`` module is the pure command
parser + label matcher; the ``pyatspi`` tree reader/actioner is Linux-only, heavy,
and opt-in (installed via system packages), lazy-loaded only when ``[pilot]
enabled``. OFF by default.
"""
