use crate::protocol::{CalibrationArtifact, CalibrationSample, InputBackend, InputEvent, CAP_HOLD};

/// Deterministic InputBackend for unit tests.
///
/// Pre-load events with `push()`, then call `start()` — all events are
/// delivered immediately over the channel and the task exits cleanly.
pub struct MockInputBackend {
    events: Vec<InputEvent>,
}

impl MockInputBackend {
    pub fn new() -> Self {
        Self { events: Vec::new() }
    }

    pub fn push(&mut self, event: InputEvent) -> &mut Self {
        self.events.push(event);
        self
    }
}

impl Default for MockInputBackend {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait::async_trait]
impl InputBackend for MockInputBackend {
    fn name(&self) -> &str {
        "mock"
    }

    fn capabilities(&self) -> &[&'static str] {
        &[CAP_HOLD]
    }

    async fn start(&mut self, tx: tokio::sync::mpsc::Sender<InputEvent>) -> anyhow::Result<()> {
        for event in self.events.drain(..) {
            tx.send(event).await.ok();
        }
        Ok(())
    }

    fn calibrate(&self, _corpus: &[CalibrationSample]) -> Option<CalibrationArtifact> {
        None
    }
}
