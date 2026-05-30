pub mod emg;
pub mod hold_detector;
pub mod keyboard;
pub mod mock;
pub mod protocol;

pub use emg::EmgYespBackend;
pub use hold_detector::HoldDetector;
pub use keyboard::{HotKey, KeyboardHoldBackend};
pub use mock::MockInputBackend;
pub use protocol::{
    CalibrationArtifact, CalibrationSample, InputBackend, InputEvent, CAP_CALIBRATION, CAP_GESTURE,
    CAP_HOLD, CAP_PARTIAL_TEXT,
};
