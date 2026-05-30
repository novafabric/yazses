class HoldDetector:
    def __init__(self, threshold_ms: int = 500) -> None:
        self._threshold = threshold_ms / 1000.0
        self._pressed_at: float | None = None
        self._space_count: int = 0
        self._triggered: bool = False

    @property
    def is_pressed(self) -> bool:
        return self._pressed_at is not None

    @property
    def leaked_count(self) -> int:
        return self._space_count

    def on_press(self, t: float) -> None:
        if self._pressed_at is None:
            self._pressed_at = t
        self._space_count += 1

    def check(self, t: float) -> bool:
        if self._pressed_at is None or self._triggered:
            return False
        if (t - self._pressed_at) >= self._threshold:
            self._triggered = True
            return True
        return False

    def reset(self) -> None:
        self._pressed_at = None
        self._space_count = 0
        self._triggered = False
