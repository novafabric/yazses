use std::sync::Arc;

use tracing::debug;

use crate::protocol::{STTBackend, TranscribeOptions, Transcript};

/// Duration-based STT dispatcher (adr-002).
///
/// For audio ≤ `threshold_s`: routes to `streaming` (Moonshine v2, 9 ms P50).
/// For audio > `threshold_s`: routes to `longform` (Whisper-large-v3-turbo).
///
/// Default threshold: **4 seconds** (heuristic from build prompt; tune against
/// the YazSes evaluation corpus once both backends are wired up).
pub struct STTRouter {
    streaming: Arc<dyn STTBackend>,
    longform: Arc<dyn STTBackend>,
    threshold_s: f32,
}

impl STTRouter {
    pub const DEFAULT_THRESHOLD_S: f32 = 4.0;

    pub fn new(
        streaming: Arc<dyn STTBackend>,
        longform: Arc<dyn STTBackend>,
        threshold_s: f32,
    ) -> Self {
        Self {
            streaming,
            longform,
            threshold_s,
        }
    }

    pub fn with_default_threshold(
        streaming: Arc<dyn STTBackend>,
        longform: Arc<dyn STTBackend>,
    ) -> Self {
        Self::new(streaming, longform, Self::DEFAULT_THRESHOLD_S)
    }

    /// Route and transcribe. The chosen backend is logged at DEBUG level.
    pub async fn transcribe(
        &self,
        audio: &[f32],
        sample_rate: u32,
        options: TranscribeOptions,
    ) -> anyhow::Result<Transcript> {
        let duration_s = audio.len() as f32 / sample_rate as f32;
        let backend = if duration_s <= self.threshold_s {
            debug!(
                duration_s,
                threshold_s = self.threshold_s,
                backend = self.streaming.name(),
                "STTRouter → streaming"
            );
            &self.streaming
        } else {
            debug!(
                duration_s,
                threshold_s = self.threshold_s,
                backend = self.longform.name(),
                "STTRouter → longform"
            );
            &self.longform
        };
        backend.transcribe(audio, sample_rate, options).await
    }

    pub fn threshold_s(&self) -> f32 {
        self.threshold_s
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mock::MockSTTBackend;

    fn make_router(threshold_s: f32) -> STTRouter {
        STTRouter::new(
            Arc::new(MockSTTBackend::new("streaming-mock", "hello")),
            Arc::new(MockSTTBackend::new("longform-mock", "world")),
            threshold_s,
        )
    }

    fn audio_of_duration(seconds: f32, sample_rate: u32) -> Vec<f32> {
        vec![0.0f32; (seconds * sample_rate as f32) as usize]
    }

    #[tokio::test]
    async fn short_audio_goes_to_streaming() {
        let router = make_router(4.0);
        let audio = audio_of_duration(2.0, 16000);
        let tx = router
            .transcribe(&audio, 16000, TranscribeOptions::default())
            .await
            .unwrap();
        assert_eq!(tx.text, "hello");
    }

    #[tokio::test]
    async fn long_audio_goes_to_longform() {
        let router = make_router(4.0);
        let audio = audio_of_duration(10.0, 16000);
        let tx = router
            .transcribe(&audio, 16000, TranscribeOptions::default())
            .await
            .unwrap();
        assert_eq!(tx.text, "world");
    }

    #[tokio::test]
    async fn exactly_at_threshold_goes_to_streaming() {
        let router = make_router(4.0);
        let audio = audio_of_duration(4.0, 16000); // exactly 4 s → streaming
        let tx = router
            .transcribe(&audio, 16000, TranscribeOptions::default())
            .await
            .unwrap();
        assert_eq!(tx.text, "hello");
    }

    #[tokio::test]
    async fn empty_audio_goes_to_streaming() {
        let router = make_router(4.0);
        let tx = router
            .transcribe(&[], 16000, TranscribeOptions::default())
            .await
            .unwrap();
        assert_eq!(tx.text, "hello");
    }

    #[tokio::test]
    async fn custom_threshold_routes_correctly() {
        let router = make_router(1.0);
        // 2 s audio with a 1 s threshold → longform
        let audio = audio_of_duration(2.0, 16000);
        let tx = router
            .transcribe(&audio, 16000, TranscribeOptions::default())
            .await
            .unwrap();
        assert_eq!(tx.text, "world");
    }
}
