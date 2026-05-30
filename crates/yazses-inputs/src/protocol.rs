use serde::{Deserialize, Serialize};

/// All events an `InputBackend` can emit.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum InputEvent {
    /// A sustained hold has crossed the threshold; `leaked` counts repeat events
    /// that fired while the key was physically held (keyboard backends only).
    HoldStart { ts: f64, leaked: u32 },
    /// Streaming partial text (e.g., from an sEMG subvocal decoder).
    PartialText { ts: f64, text: String },
    /// Gesture: kind is a backend-specific label; params carry raw data.
    Gesture {
        ts: f64,
        kind: String,
        params: serde_json::Value,
    },
    /// Hold released.
    HoldEnd { ts: f64 },
    /// Calibration completed; artifact can be persisted and re-loaded.
    CalibrationReady { artifact: CalibrationArtifact },
}

/// Opaque blob produced by `calibrate()` and re-supplied on the next start.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CalibrationArtifact {
    pub backend: String,
    pub payload: serde_json::Value,
}

/// One sample handed to `calibrate()` — a labelled event window.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CalibrationSample {
    pub label: String,
    pub data: serde_json::Value,
}

/// Stable capability labels used in `InputBackend::capabilities()`.
pub const CAP_HOLD: &str = "hold";
pub const CAP_GESTURE: &str = "gesture";
pub const CAP_PARTIAL_TEXT: &str = "partial_text";
pub const CAP_CALIBRATION: &str = "calibration";

/// Uniform interface for all input modalities (adr-005).
///
/// Implementations must be `Send + Sync` so they can be held behind an Arc.
/// `start()` is non-blocking: it spawns a task and returns immediately.
/// Events are delivered over the supplied `mpsc::Sender`.
#[async_trait::async_trait]
pub trait InputBackend: Send + Sync {
    fn name(&self) -> &str;
    fn capabilities(&self) -> &[&'static str];
    async fn start(&mut self, tx: tokio::sync::mpsc::Sender<InputEvent>) -> anyhow::Result<()>;
    fn calibrate(&self, corpus: &[CalibrationSample]) -> Option<CalibrationArtifact>;
}
