use crate::protocol::{STTBackend, TranscribeOptions, Transcript};

/// Deterministic STTBackend for unit tests.
///
/// Always returns the pre-set `response` string with zero latency.
pub struct MockSTTBackend {
    name: String,
    response: String,
}

impl MockSTTBackend {
    pub fn new(name: impl Into<String>, response: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            response: response.into(),
        }
    }
}

#[async_trait::async_trait]
impl STTBackend for MockSTTBackend {
    fn name(&self) -> &str {
        &self.name
    }

    fn preferred_max_s(&self) -> f32 {
        f32::MAX
    }

    async fn transcribe(
        &self,
        _audio: &[f32],
        _sample_rate: u32,
        _options: TranscribeOptions,
    ) -> anyhow::Result<Transcript> {
        Ok(Transcript {
            text: self.response.clone(),
            language: Some("en".into()),
            latency_ms: 0,
            confidence: 1.0,
        })
    }
}
