use crate::protocol::{
    CalibrationArtifact, CalibrationSample, InputBackend, InputEvent, CAP_CALIBRATION, CAP_HOLD,
};

/// YESP protocol message types read from the serial device.
#[derive(Debug, PartialEq, Eq)]
#[allow(dead_code)]
enum YespMessage {
    HoldStart,
    HoldEnd,
    Command(String),
    Unknown(String),
}

#[allow(dead_code)]
fn parse_yesp(line: &str) -> YespMessage {
    let line = line.trim();
    if line == "HOLD_START" {
        YespMessage::HoldStart
    } else if line == "HOLD_END" {
        YespMessage::HoldEnd
    } else if let Some(label) = line.strip_prefix("COMMAND:") {
        YespMessage::Command(label.to_string())
    } else {
        YespMessage::Unknown(line.to_string())
    }
}

/// `InputBackend` for USB-CDC EMG devices speaking the YESP protocol.
///
/// Requires the `emg` feature: `yazses-inputs = { features = ["emg"] }`.
/// If the `serialport` crate is unavailable at compile time the struct still
/// exists but `start()` returns an error immediately.
pub struct EmgYespBackend {
    device_port: String,
    baud_rate: u32,
}

impl EmgYespBackend {
    pub fn new(device_port: impl Into<String>, baud_rate: u32) -> Self {
        Self {
            device_port: device_port.into(),
            baud_rate,
        }
    }
}

#[async_trait::async_trait]
impl InputBackend for EmgYespBackend {
    fn name(&self) -> &str {
        "emg-yesp"
    }

    fn capabilities(&self) -> &[&'static str] {
        &[CAP_HOLD, CAP_CALIBRATION]
    }

    async fn start(&mut self, tx: tokio::sync::mpsc::Sender<InputEvent>) -> anyhow::Result<()> {
        start_emg(self.device_port.clone(), self.baud_rate, tx)
    }

    fn calibrate(&self, _corpus: &[CalibrationSample]) -> Option<CalibrationArtifact> {
        None
    }
}

// ── Feature-gated implementation ─────────────────────────────────────────────

#[cfg(feature = "emg")]
fn start_emg(
    device_port: String,
    baud_rate: u32,
    tx: tokio::sync::mpsc::Sender<InputEvent>,
) -> anyhow::Result<()> {
    use std::io::BufRead;
    use std::time::Duration;
    use tracing::{debug, info, warn};

    let port = serialport::new(&device_port, baud_rate)
        .timeout(Duration::from_millis(200))
        .open()
        .map_err(|e| anyhow::anyhow!("EMG serial open {device_port}: {e}"))?;

    info!(%device_port, %baud_rate, "EMG YESP backend connected");

    tokio::task::spawn_blocking(move || {
        let reader = std::io::BufReader::new(port);
        let mut hold_active = false;

        for line in reader.lines() {
            let line = match line {
                Ok(l) => l,
                Err(e) => {
                    debug!("EMG serial read error: {e}");
                    break;
                }
            };
            let ts = unix_ts();
            match parse_yesp(&line) {
                YespMessage::HoldStart if !hold_active => {
                    hold_active = true;
                    let _ = tx.blocking_send(InputEvent::HoldStart { ts, leaked: 0 });
                }
                YespMessage::HoldEnd if hold_active => {
                    hold_active = false;
                    let _ = tx.blocking_send(InputEvent::HoldEnd { ts });
                }
                YespMessage::Command(label) => {
                    let _ = tx.blocking_send(InputEvent::Gesture {
                        ts,
                        kind: "emg_command".into(),
                        params: serde_json::json!({ "label": label }),
                    });
                }
                YespMessage::Unknown(raw) => {
                    debug!(%raw, "EMG unknown message");
                }
                _ => {}
            }
        }
        warn!("EMG serial loop exited");
    });

    Ok(())
}

#[cfg(feature = "emg")]
fn unix_ts() -> f64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

#[cfg(not(feature = "emg"))]
fn start_emg(
    device_port: String,
    _baud_rate: u32,
    _tx: tokio::sync::mpsc::Sender<InputEvent>,
) -> anyhow::Result<()> {
    anyhow::bail!(
        "EMG backend is not compiled in; rebuild with `--features emg` \
         and ensure serialport is available (device_port={device_port})"
    )
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_hold_start() {
        assert_eq!(parse_yesp("HOLD_START"), YespMessage::HoldStart);
        assert_eq!(parse_yesp("HOLD_START\r\n"), YespMessage::HoldStart);
    }

    #[test]
    fn parse_hold_end() {
        assert_eq!(parse_yesp("HOLD_END"), YespMessage::HoldEnd);
    }

    #[test]
    fn parse_command() {
        assert_eq!(
            parse_yesp("COMMAND:dictate"),
            YespMessage::Command("dictate".into())
        );
    }

    #[test]
    fn parse_unknown() {
        assert_eq!(
            parse_yesp("GARBAGE"),
            YespMessage::Unknown("GARBAGE".into())
        );
    }
}
