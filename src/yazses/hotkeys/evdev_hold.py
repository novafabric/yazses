import logging
import time
from collections.abc import Callable

import evdev
from evdev import ecodes

from yazses.hotkeys.hold_detector import HoldDetector

log = logging.getLogger(__name__)


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
        devices = [evdev.InputDevice(p) for p in evdev.list_devices()]
        for dev in devices:
            caps = dev.capabilities()
            if ecodes.EV_KEY in caps and self._key_code in caps[ecodes.EV_KEY]:
                log.info("Using keyboard device: %s (%s)", dev.name, dev.path)
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
