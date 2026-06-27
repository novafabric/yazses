import logging
import time
from collections.abc import Callable

import evdev
from evdev import ecodes

from yazses.hotkeys.hold_detector import HoldDetector

log = logging.getLogger(__name__)

# Substrings that mark a device as a virtual/injected input rather than a real
# keyboard. Injection tools (ydotool, wtype) create uinput devices that
# advertise the full key range, so they must never be chosen as the hotkey
# source — they only ever carry synthetic events, never the user's keypresses.
_VIRTUAL_NAME_MARKERS = ("ydotool", "uinput", "virtual", "wtype", "yazses")


def _is_virtual_device(dev: "evdev.InputDevice") -> bool:
    name = (dev.name or "").lower()
    return any(marker in name for marker in _VIRTUAL_NAME_MARKERS)


def _looks_like_keyboard(dev: "evdev.InputDevice") -> bool:
    """True if the device exposes a full letter row plus Enter (a real keyboard,
    not a power button, hotkey block, or partial keypad)."""
    keys = set(dev.capabilities().get(ecodes.EV_KEY, ()))
    letters = {getattr(ecodes, f"KEY_{c}") for c in "QWERTYUIOPASDFGHJKLZXCVBNM"}
    return ecodes.KEY_ENTER in keys and letters.issubset(keys)


class EvdevHoldListener:
    def __init__(
        self,
        threshold_ms: int,
        on_hold_start: Callable[[int], None],
        on_hold_end: Callable[[], None],
        key_code: int = ecodes.KEY_SPACE,
    ) -> None:
        self._detector = HoldDetector(threshold_ms=threshold_ms)
        self._on_hold_start = on_hold_start
        self._on_hold_end = on_hold_end
        self._key_code = key_code
        self._recording = False
        self._stopping = False
        self._keyboard: evdev.InputDevice | None = None

    def _find_keyboard(self) -> evdev.InputDevice:
        devices = [evdev.InputDevice(p) for p in sorted(evdev.list_devices())]
        candidates = [
            dev
            for dev in devices
            if ecodes.EV_KEY in dev.capabilities()
            and self._key_code in dev.capabilities()[ecodes.EV_KEY]
        ]
        real = [dev for dev in candidates if not _is_virtual_device(dev)]

        # Prefer a real device that looks like a full keyboard, then any real
        # device, then (with a warning) a virtual one as a last resort.
        for dev in real:
            if _looks_like_keyboard(dev):
                log.info("Using keyboard device: %s (%s)", dev.name, dev.path)
                return dev
        if real:
            dev = real[0]
            log.info("Using keyboard device: %s (%s)", dev.name, dev.path)
            return dev
        if candidates:
            dev = candidates[0]
            log.warning(
                "Only a virtual input device (%s) exposes the hotkey; real key "
                "presses may not be detected. Ensure your hardware keyboard is "
                "in /dev/input and you are in the 'input' group.",
                dev.name,
            )
            return dev
        raise RuntimeError(
            "No keyboard device found in /dev/input. "
            "Ensure you are in the 'input' group: sudo usermod -aG input $USER"
        )

    def run(self) -> None:
        self._keyboard = self._find_keyboard()
        try:
            for event in self._keyboard.read_loop():
                if self._stopping:
                    break
                if event.type != ecodes.EV_KEY or event.code != self._key_code:
                    continue

                t = time.monotonic()

                if event.value in (1, 2):  # press (1) or key-repeat (2)
                    if event.value == 1:  # only count the initial press as a leak
                        self._detector.on_press(t)
                    if not self._recording and self._detector.check(t):
                        self._recording = True
                        leaked = self._detector.leaked_count
                        log.debug("Hold detected, leaked count: %d", leaked)
                        self._on_hold_start(leaked)

                elif event.value == 0:  # release
                    was_recording = self._recording
                    self._recording = False
                    self._detector.reset()
                    if was_recording:
                        self._on_hold_end()
        except OSError:
            # stop() closes the device fd, which makes read_loop raise.
            if not self._stopping:
                raise

    def stop(self) -> None:
        self._stopping = True
        kb = self._keyboard
        if kb is not None:
            try:
                kb.close()
            except OSError:
                pass
