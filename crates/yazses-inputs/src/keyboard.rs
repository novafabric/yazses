use tracing::{debug, info, warn};

use crate::hold_detector::HoldDetector;
use crate::protocol::{CalibrationArtifact, CalibrationSample, InputBackend, InputEvent, CAP_HOLD};

/// Configures which physical key is used as the push-to-talk trigger.
#[derive(Debug, Clone)]
pub enum HotKey {
    RightAlt,
    LeftAlt,
    RightCtrl,
    LeftCtrl,
    /// Raw evdev key code (Linux) or virtual-key code (Windows/macOS).
    Raw(u32),
}

impl std::str::FromStr for HotKey {
    type Err = std::convert::Infallible;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Ok(match s {
            "right_alt" => Self::RightAlt,
            "left_alt" => Self::LeftAlt,
            "right_ctrl" => Self::RightCtrl,
            "left_ctrl" => Self::LeftCtrl,
            other => {
                if let Ok(n) = other.parse::<u32>() {
                    Self::Raw(n)
                } else {
                    warn!(%other, "unknown hotkey name; defaulting to right_alt");
                    Self::RightAlt
                }
            }
        })
    }
}

#[cfg(target_os = "linux")]
impl HotKey {
    pub fn evdev_code(&self) -> evdev::KeyCode {
        match self {
            Self::RightAlt => evdev::KeyCode::KEY_RIGHTALT,
            Self::LeftAlt => evdev::KeyCode::KEY_LEFTALT,
            Self::RightCtrl => evdev::KeyCode::KEY_RIGHTCTRL,
            Self::LeftCtrl => evdev::KeyCode::KEY_LEFTCTRL,
            Self::Raw(c) => evdev::KeyCode(*c as u16),
        }
    }
}

/// Keyboard hold-to-talk backend.
///
/// Platform support:
/// - **Linux** (`target_os = "linux"`): uses evdev to read from all keyboard
///   devices found under `/dev/input/`. Falls back gracefully if no devices
///   have the needed permission.
/// - **macOS / Windows**: stub — logs a warning and does nothing (full port
///   is Phase 6, per `10_build_prompt.md`).
pub struct KeyboardHoldBackend {
    hotkey: HotKey,
    threshold_ms: u32,
}

impl KeyboardHoldBackend {
    pub fn new(hotkey: HotKey, threshold_ms: u32) -> Self {
        Self {
            hotkey,
            threshold_ms,
        }
    }
}

#[async_trait::async_trait]
impl InputBackend for KeyboardHoldBackend {
    fn name(&self) -> &str {
        "keyboard-hold"
    }

    fn capabilities(&self) -> &[&'static str] {
        &[CAP_HOLD]
    }

    async fn start(&mut self, tx: tokio::sync::mpsc::Sender<InputEvent>) -> anyhow::Result<()> {
        start_platform(self.hotkey.clone(), self.threshold_ms, tx).await
    }

    fn calibrate(&self, _corpus: &[CalibrationSample]) -> Option<CalibrationArtifact> {
        None
    }
}

// ── Linux implementation ──────────────────────────────────────────────────────

#[cfg(target_os = "linux")]
async fn start_platform(
    hotkey: HotKey,
    threshold_ms: u32,
    tx: tokio::sync::mpsc::Sender<InputEvent>,
) -> anyhow::Result<()> {
    let target_key = hotkey.evdev_code();

    let keyboards: Vec<_> = evdev::enumerate()
        .filter_map(|(_path, dev)| {
            if dev.supported_keys().is_some_and(|k| k.contains(target_key)) {
                Some(dev)
            } else {
                None
            }
        })
        .collect();

    if keyboards.is_empty() {
        warn!(
            key_code = target_key.0,
            "no evdev keyboard devices found with the target key; \
             check /dev/input permissions (udev rule or `input` group)"
        );
        return Ok(());
    }

    info!(
        count = keyboards.len(),
        key_code = target_key.0,
        "keyboard hold backend starting"
    );

    for device in keyboards {
        let tx = tx.clone();
        tokio::task::spawn_blocking(move || {
            evdev_poll_loop(device, target_key, threshold_ms, tx);
        });
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn evdev_poll_loop(
    mut device: evdev::Device,
    target_key: evdev::KeyCode,
    threshold_ms: u32,
    tx: tokio::sync::mpsc::Sender<InputEvent>,
) {
    use std::time::Instant;
    let mut det = HoldDetector::new(threshold_ms);

    loop {
        let events = match device.fetch_events() {
            Ok(e) => e,
            Err(e) => {
                debug!("evdev fetch_events error: {e}");
                break;
            }
        };
        for ev in events {
            if ev.event_type() != evdev::EventType::KEY || ev.code() != target_key.0 {
                continue;
            }
            let now = Instant::now();
            let ts = unix_ts();
            match ev.value() {
                1 => {
                    // key down (initial press)
                    det.on_press(now);
                    if det.check(now) {
                        let leaked = det.leaked_count();
                        let _ = tx.blocking_send(InputEvent::HoldStart { ts, leaked });
                    }
                }
                2 => {
                    // key repeat
                    det.on_press(now);
                    if det.check(now) {
                        let leaked = det.leaked_count();
                        let _ = tx.blocking_send(InputEvent::HoldStart { ts, leaked });
                    }
                }
                0 => {
                    // key up
                    if det.is_pressed() {
                        if det.check(now) {
                            let leaked = det.leaked_count();
                            let _ = tx.blocking_send(InputEvent::HoldStart { ts, leaked });
                        }
                        let _ = tx.blocking_send(InputEvent::HoldEnd { ts });
                    }
                    det.reset();
                }
                _ => {}
            }
        }
    }
}

#[cfg(target_os = "linux")]
fn unix_ts() -> f64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

// ── Non-Linux stub ────────────────────────────────────────────────────────────

#[cfg(not(target_os = "linux"))]
async fn start_platform(
    _hotkey: HotKey,
    _threshold_ms: u32,
    _tx: tokio::sync::mpsc::Sender<InputEvent>,
) -> anyhow::Result<()> {
    warn!(
        "KeyboardHoldBackend is not yet implemented on this platform (Phase 6). \
         Hold-to-talk will be inactive."
    );
    Ok(())
}
