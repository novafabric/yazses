"""EMG silent speech backend — implements HotkeyBackend over USB CDC serial (YESP protocol).

Devices communicate with the daemon by sending newline-delimited ASCII messages at
115200 baud. See docs/emg-protocol.md for the full YESP specification.

pyserial is an optional dependency; if not installed the backend is disabled and
run() returns immediately.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)

try:
    import serial  # type: ignore[import-untyped]

    _SERIAL_AVAILABLE = True
except ImportError:
    serial = None  # type: ignore[assignment]
    _SERIAL_AVAILABLE = False


class EMGBackend:
    """HotkeyBackend implementation for USB-CDC EMG devices speaking YESP.

    Conforms to the HotkeyBackend Protocol (duck-typed, no explicit inheritance).

    Parameters
    ----------
    device_port:
        OS serial port path, e.g. ``/dev/ttyACM0`` or ``COM3``.
    baud_rate:
        Serial link speed. YESP specifies 115200.
    on_hold_start:
        Called with the number of leaked characters (always 0 for EMG) when
        a HOLD_START or COMMAND message is received.
    on_hold_end:
        Called when HOLD_END or COMMAND message is processed.
    command_map:
        Mapping from COMMAND label to intent/action string. When a
        ``COMMAND:<label>`` message arrives and the label is present in this
        dict, the mapped value is stored as ``_pending_command`` and a
        synthetic hold-start + hold-end cycle is fired so the daemon grammar
        pipeline receives it as if dictated.
    """

    def __init__(
        self,
        device_port: str,
        baud_rate: int = 115200,
        on_hold_start: Callable[[int], None] = lambda n: None,
        on_hold_end: Callable[[], None] = lambda: None,
        command_map: dict[str, str] | None = None,
    ) -> None:
        self._device_port = device_port
        self._baud_rate = baud_rate
        self._on_hold_start = on_hold_start
        self._on_hold_end = on_hold_end
        self._command_map: dict[str, str] = command_map if command_map is not None else {}
        self._stop_event = threading.Event()
        self._pending_command: str | None = None

    # ------------------------------------------------------------------
    # HotkeyBackend protocol
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Open the serial port and dispatch YESP messages until stop() is called.

        If pyserial is not installed this method logs a warning and returns
        immediately (no-op mode).
        """
        if not _SERIAL_AVAILABLE:
            log.warning(
                "EMGBackend: pyserial is not installed; EMG silent-speech input is disabled. "
                "Install it with: pip install pyserial"
            )
            return

        log.info("EMGBackend: opening %s at %d baud", self._device_port, self._baud_rate)

        try:
            ser = serial.Serial(self._device_port, self._baud_rate, timeout=1.0)
        except serial.SerialException as exc:
            log.warning("EMGBackend: could not open serial port %s: %s", self._device_port, exc)
            return

        log.info("EMGBackend: connected to %s", self._device_port)

        with ser:
            while not self._stop_event.is_set():
                try:
                    raw = ser.readline()
                except serial.SerialException as exc:
                    log.warning("EMGBackend: serial read error on %s: %s", self._device_port, exc)
                    break

                line = raw.decode("ascii", errors="ignore").strip()
                if not line:
                    # Timeout — no data within the 1-second window; loop back.
                    continue

                self._dispatch(line)

        log.info("EMGBackend: serial loop exited for %s", self._device_port)

    def stop(self) -> None:
        """Signal run() to exit cleanly at the next read timeout."""
        log.debug("EMGBackend: stop() called")
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dispatch(self, line: str) -> None:
        """Parse a single YESP line and call the appropriate callbacks."""
        if line == "HOLD_START":
            log.debug("EMGBackend: HOLD_START")
            self._on_hold_start(0)

        elif line == "HOLD_END":
            log.debug("EMGBackend: HOLD_END")
            self._on_hold_end()

        elif line.startswith("COMMAND:"):
            label = line[len("COMMAND:"):]
            action = self._command_map.get(label)
            if action is None:
                log.debug("EMGBackend: COMMAND label %r not in command_map, ignoring", label)
                return
            log.debug("EMGBackend: COMMAND %r -> %r", label, action)
            self._pending_command = action
            # Simulate an instantaneous press+release so the daemon grammar
            # pipeline receives the mapped action string as dictated text.
            self._on_hold_start(0)
            self._on_hold_end()

        elif line.startswith("TEXT:"):
            text = line[len("TEXT:"):]
            log.debug("EMGBackend: TEXT (reserved, no-op in v0.4.0): %r", text)

        elif line == "HEARTBEAT":
            log.debug("EMGBackend: HEARTBEAT")

        else:
            log.debug("EMGBackend: unknown YESP message: %r", line)
