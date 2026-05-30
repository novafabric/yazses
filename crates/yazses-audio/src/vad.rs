/// RMS-based voice activity gate.
///
/// Port of `src/yazses/audio/vad.py` and `vad_calibrated.py`. No ONNX model
/// required; matches v0.4 behavior exactly. Silero VAD will be added behind
/// a feature flag in Phase 2.
#[derive(Debug, Clone)]
pub struct VadGate {
    threshold: f32,
}

impl VadGate {
    pub const DEFAULT_THRESHOLD: f32 = 0.01;

    pub fn new(threshold: f32) -> Self {
        Self { threshold }
    }

    /// `true` when the frame is silent (mean absolute amplitude < threshold).
    pub fn is_silent(&self, frame: &[f32]) -> bool {
        if frame.is_empty() {
            return true;
        }
        let mean_abs: f32 = frame.iter().map(|s| s.abs()).sum::<f32>() / frame.len() as f32;
        mean_abs < self.threshold
    }

    /// Convenience: `true` when the frame contains speech.
    pub fn is_speech(&self, frame: &[f32]) -> bool {
        !self.is_silent(frame)
    }
}

impl Default for VadGate {
    fn default() -> Self {
        Self::new(Self::DEFAULT_THRESHOLD)
    }
}

/// Mean absolute amplitude of a frame (0.0 for an empty frame).
fn mean_abs(frame: &[f32]) -> f32 {
    if frame.is_empty() {
        return 0.0;
    }
    frame.iter().map(|s| s.abs()).sum::<f32>() / frame.len() as f32
}

/// Stateful endpointing gate with **hysteresis** and a **hangover** window.
///
/// The plain [`VadGate`] makes an independent decision per frame, so a quiet
/// trailing syllable gets clipped and a momentary dip mid-word can split an
/// utterance. This gate fixes both, the way Silero-style endpointers and the
/// VAD literature recommend:
///
/// * **Hysteresis** — speech must cross a higher `start_threshold` to begin,
///   but only drops below a lower `stop_threshold` to end. The gap prevents
///   rapid on/off flicker around a single threshold.
/// * **Hangover** — once speaking, it stays "in speech" until
///   `hangover_frames` *consecutive* sub-threshold frames have passed, so brief
///   pauses and quiet word endings are kept rather than truncated.
///
/// Feed one frame at a time via [`update`](Self::update); it returns whether the
/// stream is currently inside a speech segment. Pure logic, no model.
#[derive(Debug, Clone)]
pub struct HysteresisGate {
    start_threshold: f32,
    stop_threshold: f32,
    hangover_frames: u32,
    speaking: bool,
    silent_run: u32,
}

impl HysteresisGate {
    /// Default hangover, in frames, used by [`with_base`](Self::with_base).
    pub const DEFAULT_HANGOVER_FRAMES: u32 = 8;

    pub fn new(start_threshold: f32, stop_threshold: f32, hangover_frames: u32) -> Self {
        Self {
            start_threshold,
            stop_threshold,
            hangover_frames,
            speaking: false,
            silent_run: 0,
        }
    }

    /// Derive a gate from a single calibrated `base` threshold (e.g. the
    /// `accessibility.vad_threshold`): start at `base`, keep going down to
    /// `base / 2`, with the default hangover.
    pub fn with_base(base: f32) -> Self {
        Self::new(base, base * 0.5, Self::DEFAULT_HANGOVER_FRAMES)
    }

    pub fn is_speaking(&self) -> bool {
        self.speaking
    }

    /// Feed one frame; returns `true` if the stream is currently in a speech
    /// segment (including the hangover tail).
    pub fn update(&mut self, frame: &[f32]) -> bool {
        let level = mean_abs(frame);
        if self.speaking {
            if level < self.stop_threshold {
                self.silent_run += 1;
                if self.silent_run > self.hangover_frames {
                    self.speaking = false;
                    self.silent_run = 0;
                }
            } else {
                self.silent_run = 0; // a loud frame resets the hangover countdown
            }
        } else if level >= self.start_threshold {
            self.speaking = true;
            self.silent_run = 0;
        }
        self.speaking
    }

    /// Reset to the initial (not-speaking) state for a new utterance.
    pub fn reset(&mut self) {
        self.speaking = false;
        self.silent_run = 0;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_frame_is_silent() {
        assert!(VadGate::default().is_silent(&[]));
    }

    #[test]
    fn silence_below_threshold() {
        let gate = VadGate::new(0.01);
        let silent: Vec<f32> = vec![0.005; 1600];
        assert!(gate.is_silent(&silent));
    }

    #[test]
    fn speech_above_threshold() {
        let gate = VadGate::new(0.01);
        let speech: Vec<f32> = vec![0.1; 1600];
        assert!(gate.is_speech(&speech));
    }

    #[test]
    fn just_below_threshold_is_silent() {
        // `< threshold` so a value just below is silent.
        let gate = VadGate::new(0.01);
        let frame: Vec<f32> = vec![0.0099; 1600];
        assert!(gate.is_silent(&frame));
    }

    #[test]
    fn mixed_pos_neg_uses_absolute_value() {
        let gate = VadGate::new(0.01);
        // Mean of abs([−0.05, 0.05]) = 0.05 → speech.
        let frame = vec![-0.05f32, 0.05];
        assert!(gate.is_speech(&frame));
    }

    // ── HysteresisGate ───────────────────────────────────────────────────────

    fn frame(level: f32) -> Vec<f32> {
        vec![level; 512]
    }

    #[test]
    fn hysteresis_starts_only_above_start_threshold() {
        let mut g = HysteresisGate::new(0.02, 0.01, 3);
        // Between stop and start: must NOT trigger onset.
        assert!(!g.update(&frame(0.015)));
        assert!(!g.is_speaking());
        // At/above start: onset.
        assert!(g.update(&frame(0.02)));
        assert!(g.is_speaking());
    }

    #[test]
    fn hysteresis_keeps_speaking_through_brief_dips() {
        let mut g = HysteresisGate::new(0.02, 0.01, 3);
        g.update(&frame(0.05)); // onset
        // A quiet frame below stop, but within the hangover window → still speech.
        assert!(g.update(&frame(0.0)));
        assert!(g.update(&frame(0.0)));
        // A loud frame resets the hangover so it keeps going.
        assert!(g.update(&frame(0.05)));
        assert!(g.is_speaking());
    }

    #[test]
    fn hysteresis_ends_after_hangover_frames() {
        let mut g = HysteresisGate::new(0.02, 0.01, 3);
        g.update(&frame(0.05)); // onset
        // hangover_frames = 3 → speech ends only after the 4th consecutive quiet frame.
        assert!(g.update(&frame(0.0))); // 1
        assert!(g.update(&frame(0.0))); // 2
        assert!(g.update(&frame(0.0))); // 3
        assert!(!g.update(&frame(0.0))); // 4 → end
        assert!(!g.is_speaking());
    }

    #[test]
    fn hysteresis_reset_clears_state() {
        let mut g = HysteresisGate::with_base(0.01);
        g.update(&frame(0.5));
        assert!(g.is_speaking());
        g.reset();
        assert!(!g.is_speaking());
    }

    #[test]
    fn with_base_sets_lower_stop_threshold() {
        // start = base, stop = base/2 → a frame between the two sustains but
        // does not start speech.
        let mut g = HysteresisGate::with_base(0.02);
        assert!(!g.update(&frame(0.012))); // below start (0.02): no onset
        g.update(&frame(0.05)); // onset
        assert!(g.update(&frame(0.012))); // above stop (0.01): still speaking
    }
}
