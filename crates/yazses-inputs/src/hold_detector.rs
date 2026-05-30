use std::time::{Duration, Instant};

/// Hold-key state machine — tracks press → hold threshold → release.
///
/// This is a direct port of the Python `HoldDetector` from
/// `src/yazses/hotkeys/hold_detector.py`. Platform-independent pure logic;
/// keyboard backends drive it by calling `on_press` / `check` / `reset`.
#[derive(Debug)]
pub struct HoldDetector {
    threshold: Duration,
    pressed_at: Option<Instant>,
    leaked: u32,
    triggered: bool,
}

impl HoldDetector {
    pub fn new(threshold_ms: u32) -> Self {
        Self {
            threshold: Duration::from_millis(threshold_ms as u64),
            pressed_at: None,
            leaked: 0,
            triggered: false,
        }
    }

    pub fn is_pressed(&self) -> bool {
        self.pressed_at.is_some()
    }

    /// Count of key-repeat events that arrived while the key was down.
    pub fn leaked_count(&self) -> u32 {
        self.leaked
    }

    /// Called on every key-down event (initial press and auto-repeat).
    pub fn on_press(&mut self, now: Instant) {
        if self.pressed_at.is_none() {
            self.pressed_at = Some(now);
        }
        self.leaked += 1;
    }

    /// Returns `true` exactly once — when the hold threshold is first crossed.
    pub fn check(&mut self, now: Instant) -> bool {
        if let Some(start) = self.pressed_at {
            if !self.triggered && now.duration_since(start) >= self.threshold {
                self.triggered = true;
                return true;
            }
        }
        false
    }

    pub fn reset(&mut self) {
        self.pressed_at = None;
        self.leaked = 0;
        self.triggered = false;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{Duration, Instant};

    #[test]
    fn below_threshold_does_not_trigger() {
        let mut det = HoldDetector::new(500);
        let t0 = Instant::now();
        det.on_press(t0);
        assert!(!det.check(t0 + Duration::from_millis(499)));
    }

    #[test]
    fn at_threshold_triggers_once() {
        let mut det = HoldDetector::new(500);
        let t0 = Instant::now();
        det.on_press(t0);
        let t1 = t0 + Duration::from_millis(500);
        assert!(det.check(t1));
        // Second check does not fire again.
        assert!(!det.check(t1 + Duration::from_millis(10)));
    }

    #[test]
    fn reset_clears_state() {
        let mut det = HoldDetector::new(200);
        let t0 = Instant::now();
        det.on_press(t0);
        det.check(t0 + Duration::from_millis(200));
        det.reset();
        assert!(!det.is_pressed());
        assert_eq!(det.leaked_count(), 0);
        // Re-arm — should trigger fresh after reset.
        det.on_press(t0);
        assert!(det.check(t0 + Duration::from_millis(300)));
    }

    #[test]
    fn leaked_count_increments_on_repeat() {
        let mut det = HoldDetector::new(500);
        let t0 = Instant::now();
        det.on_press(t0);
        det.on_press(t0 + Duration::from_millis(10));
        det.on_press(t0 + Duration::from_millis(20));
        assert_eq!(det.leaked_count(), 3);
    }
}
