use serde::{Deserialize, Serialize};

/// Completed transcription result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Transcript {
    /// Cleaned transcribed text.
    pub text: String,
    /// BCP-47 language tag detected or forced (e.g. `"en"`, `"fa"`).
    pub language: Option<String>,
    /// Wall-clock inference time in milliseconds.
    pub latency_ms: u64,
    /// Model-reported confidence in [0, 1]; `1.0` if the backend does not
    /// expose a probability.
    pub confidence: f32,
}

/// Options threaded through a single transcription call.
#[derive(Debug, Clone, Default)]
pub struct TranscribeOptions {
    /// LSP-injected context string prepended to the decode (Whisper
    /// `initial_prompt`). Streaming backends ignore this field.
    pub initial_prompt: Option<String>,
    /// Force a specific language; `None` → auto-detect.
    pub language: Option<String>,
}

/// Uniform interface for all STT backends (adr-002).
///
/// Both the streaming Moonshine path and the long-form Whisper path implement
/// this trait. `STTRouter` dispatches between them based on audio duration.
///
/// Implementations must be `Send + Sync` so they can be stored in an `Arc`.
#[async_trait::async_trait]
pub trait STTBackend: Send + Sync {
    /// Short human-readable name used in logs and status responses.
    fn name(&self) -> &str;

    /// Soft upper bound (seconds) this backend handles well.
    ///
    /// `STTRouter` uses this to select between backends. A value of
    /// `f32::MAX` signals "no upper bound" (long-form path).
    fn preferred_max_s(&self) -> f32;

    /// Transcribe a complete audio buffer.
    ///
    /// `audio`: mono f32 PCM.
    /// `sample_rate`: samples per second (16 000 for Moonshine; any for Whisper).
    async fn transcribe(
        &self,
        audio: &[f32],
        sample_rate: u32,
        options: TranscribeOptions,
    ) -> anyhow::Result<Transcript>;
}
