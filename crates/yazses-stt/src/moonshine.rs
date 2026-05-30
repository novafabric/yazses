use crate::protocol::{STTBackend, TranscribeOptions, Transcript};

/// Streaming STT backend using Moonshine v2 via moonshine-voice 0.0.59+.
///
/// Feature gate: `--features moonshine` + `pip install moonshine-voice`.
pub struct MoonshineV2Backend {
    #[allow(dead_code)]
    model_name: String,
    #[cfg(feature = "moonshine")]
    transcriber: pyo3::Py<pyo3::PyAny>,
}

impl MoonshineV2Backend {
    /// Load a Moonshine model.
    /// `model_name`: asset directory name e.g. `"tiny-en"`, `"base-en"`.
    pub fn new(model_name: impl Into<String>) -> anyhow::Result<Self> {
        let model_name = model_name.into();
        #[cfg(feature = "moonshine")]
        {
            load_transcriber_py(&model_name).map(|transcriber| Self { model_name, transcriber })
        }
        #[cfg(not(feature = "moonshine"))]
        {
            anyhow::bail!(
                "MoonshineV2Backend requires `--features moonshine` and \
                 `pip install moonshine-voice`. (model_name={model_name})"
            )
        }
    }

    /// Synchronous transcription — call from inside `block_in_place` or a blocking thread.
    #[cfg(feature = "moonshine")]
    pub fn transcribe_sync(&self, audio: &[f32]) -> anyhow::Result<Transcript> {
        transcribe_blocking(&self.transcriber, audio, &self.model_name)
    }
}

#[async_trait::async_trait]
impl STTBackend for MoonshineV2Backend {
    fn name(&self) -> &str {
        "moonshine-v2"
    }

    fn preferred_max_s(&self) -> f32 {
        4.0
    }

    async fn transcribe(
        &self,
        audio: &[f32],
        _sample_rate: u32,
        _options: TranscribeOptions,
    ) -> anyhow::Result<Transcript> {
        #[cfg(feature = "moonshine")]
        {
            use pyo3::Python;
            let audio = audio.to_vec();
            let model_name = self.model_name.clone();
            // Clone the Py<PyAny> ref while holding the GIL (pyo3 0.22+ API).
            let transcriber = Python::attach(|py| self.transcriber.clone_ref(py));
            tokio::task::block_in_place(move || {
                transcribe_blocking(&transcriber, &audio, &model_name)
            })
        }
        #[cfg(not(feature = "moonshine"))]
        {
            let _ = audio;
            anyhow::bail!("MoonshineV2Backend not compiled in (missing `moonshine` feature)")
        }
    }
}

// ── PyO3 implementation ───────────────────────────────────────────────────────

#[cfg(feature = "moonshine")]
fn load_transcriber_py(model_name: &str) -> anyhow::Result<pyo3::Py<pyo3::PyAny>> {
    use pyo3::prelude::*;
    use tracing::info;

    info!(%model_name, "loading Moonshine model");

    Python::attach(|py| -> PyResult<pyo3::Py<pyo3::PyAny>> {
        let utils = py.import("moonshine_voice.utils").map_err(|e| {
            pyo3::exceptions::PyImportError::new_err(format!(
                "cannot import moonshine_voice.utils: {e}\n\
                 Ensure moonshine-voice is installed: pip install moonshine-voice"
            ))
        })?;
        let model_path: String = utils
            .getattr("get_model_path")?
            .call1((model_name,))?
            .str()?
            .extract()?;

        let api = py.import("moonshine_voice.moonshine_api")?;
        let arch_cls = api.getattr("ModelArch")?;
        let arch = if model_name.contains("small-streaming") {
            arch_cls.getattr("SMALL_STREAMING")?
        } else if model_name.contains("base-streaming") {
            arch_cls.getattr("BASE_STREAMING")?
        } else if model_name.contains("tiny-streaming") {
            arch_cls.getattr("TINY_STREAMING")?
        } else if model_name.contains("base") {
            arch_cls.getattr("BASE")?
        } else {
            arch_cls.getattr("TINY")?
        };

        let transcriber_mod = py.import("moonshine_voice.transcriber")?;
        let transcriber_cls = transcriber_mod.getattr("Transcriber")?;
        let kwargs = pyo3::types::PyDict::new(py);
        kwargs.set_item("model_arch", arch)?;
        let transcriber = transcriber_cls.call((model_path.as_str(),), Some(&kwargs))?;

        info!(%model_name, %model_path, "Moonshine model loaded");
        Ok(transcriber.into())
    })
    .map_err(|e| anyhow::anyhow!("Moonshine load failed: {e}"))
}

#[cfg(feature = "moonshine")]
pub(crate) fn transcribe_blocking(
    transcriber: &pyo3::Py<pyo3::PyAny>,
    audio: &[f32],
    model_name: &str,
) -> anyhow::Result<Transcript> {
    use pyo3::prelude::*;
    use pyo3::types::PyList;
    use std::time::Instant;

    let t0 = Instant::now();

    let text = Python::attach(|py| -> PyResult<String> {
        let t = transcriber.bind(py);
        let py_audio = PyList::new(py, audio)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("PyList: {e}")))?;
        let result = t
            .call_method1("transcribe_without_streaming", (py_audio, 16000u32))
            .map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(format!(
                    "transcribe_without_streaming: {e}"
                ))
            })?;
        let mut parts = Vec::new();
        for line in result.getattr("lines")?.try_iter()? {
            let text: String = line?.getattr("text")?.extract()?;
            parts.push(text);
        }
        Ok(parts.join(" "))
    })
    .map_err(|e| anyhow::anyhow!("Moonshine transcription error: {e}"))?;

    let latency_ms = t0.elapsed().as_millis() as u64;
    tracing::debug!(latency_ms, %model_name, "Moonshine transcription done");

    Ok(Transcript {
        text,
        language: Some("en".into()),
        latency_ms,
        confidence: 1.0,
    })
}
