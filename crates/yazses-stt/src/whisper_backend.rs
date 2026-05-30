use crate::protocol::{STTBackend, TranscribeOptions, Transcript};

/// Long-form STT backend using whisper.cpp.
///
/// **Feature gate:** requires `--features whisper`, cmake, and a C++ compiler.
/// Model file loaded from `model_path` (`.bin` / `.gguf`).
pub struct WhisperBackend {
    #[allow(dead_code)]
    model_path: String,
    #[cfg(feature = "whisper")]
    #[allow(dead_code)] // held to keep the context alive; state borrows from it
    ctx: std::sync::Arc<whisper_rs::WhisperContext>,
    /// Reused across utterances — avoids re-allocating ~230 MB of compute
    /// buffers (kv-cache + encode/decode scratch) on every transcription.
    #[cfg(feature = "whisper")]
    state: tokio::sync::Mutex<whisper_rs::WhisperState>,
}

impl WhisperBackend {
    pub fn new(model_path: impl Into<String>) -> anyhow::Result<Self> {
        let model_path = model_path.into();
        #[cfg(feature = "whisper")]
        {
            // Redirect all whisper.cpp / GGML stdout logs to tracing.
            // Without this every utterance prints ~20 lines of C-level debug.
            whisper_rs::install_logging_hooks();

            let ctx = load_whisper_ctx(&model_path)?;
            let ctx = std::sync::Arc::new(ctx);
            let state = ctx
                .create_state()
                .map_err(|e| anyhow::anyhow!("creating Whisper state: {e}"))?;
            Ok(Self {
                model_path,
                ctx,
                state: tokio::sync::Mutex::new(state),
            })
        }
        #[cfg(not(feature = "whisper"))]
        {
            anyhow::bail!(
                "WhisperBackend requires the `whisper` feature \
                 (requires cmake + C++ compiler). model_path={model_path}"
            )
        }
    }
}

#[async_trait::async_trait]
impl STTBackend for WhisperBackend {
    fn name(&self) -> &str {
        "whisper-base"
    }

    fn preferred_max_s(&self) -> f32 {
        f32::MAX
    }

    async fn transcribe(
        &self,
        audio: &[f32],
        sample_rate: u32,
        options: TranscribeOptions,
    ) -> anyhow::Result<Transcript> {
        #[cfg(feature = "whisper")]
        {
            let audio = audio.to_vec();
            let mut state = self.state.lock().await;
            tokio::task::block_in_place(|| {
                transcribe_with_state(&mut state, &audio, sample_rate, options)
            })
        }
        #[cfg(not(feature = "whisper"))]
        {
            let _ = (audio, sample_rate, options);
            anyhow::bail!("WhisperBackend not compiled in (missing `whisper` feature)")
        }
    }
}

// ── whisper-rs implementation ─────────────────────────────────────────────────

#[cfg(feature = "whisper")]
fn load_whisper_ctx(model_path: &str) -> anyhow::Result<whisper_rs::WhisperContext> {
    use tracing::info;
    info!(%model_path, "loading Whisper model");
    let params = whisper_rs::WhisperContextParameters::default();
    whisper_rs::WhisperContext::new_with_params(model_path, params)
        .map_err(|e| anyhow::anyhow!("loading Whisper model {model_path}: {e}"))
}

#[cfg(feature = "whisper")]
fn transcribe_with_state(
    state: &mut whisper_rs::WhisperState,
    audio: &[f32],
    _sample_rate: u32,
    options: TranscribeOptions,
) -> anyhow::Result<Transcript> {
    use std::time::Instant;
    let t0 = Instant::now();

    let mut params =
        whisper_rs::FullParams::new(whisper_rs::SamplingStrategy::Greedy { best_of: 1 });
    params.set_print_special(false);
    params.set_print_progress(false);
    params.set_print_realtime(false);
    params.set_print_timestamps(false);

    if let Some(lang) = &options.language {
        params.set_language(Some(lang));
    }
    if let Some(prompt) = &options.initial_prompt {
        params.set_initial_prompt(prompt);
    }

    state
        .full(params, audio)
        .map_err(|e| anyhow::anyhow!("Whisper full() failed: {e}"))?;

    let n_segments = state.full_n_segments();
    let mut text = String::new();
    for i in 0..n_segments {
        if let Some(seg) = state.get_segment(i) {
            if let Ok(s) = seg.to_str() {
                text.push_str(s);
            }
        }
    }

    let lang = whisper_rs::get_lang_str(state.full_lang_id_from_state()).map(|s| s.to_string());
    let latency_ms = t0.elapsed().as_millis() as u64;
    tracing::info!(latency_ms, %text, "Whisper transcription done");

    Ok(Transcript {
        text: text.trim().to_string(),
        language: lang,
        latency_ms,
        confidence: 1.0,
    })
}
