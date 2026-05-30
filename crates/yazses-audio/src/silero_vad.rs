/// Silero VAD v4 — ONNX-based speech/non-speech classifier.
///
/// **Feature gate:** `--features silero`. Requires the Silero VAD ONNX model
/// (`silero_vad.onnx`) placed at `~/.local/share/yazses/models/silero_vad.onnx`
/// or any path passed to [`SileroVad::new`].
///
/// Produces per-chunk speech probabilities; returns `true` for chunks where
/// P(speech) ≥ `threshold` (default 0.5).
///
/// Latency: ~1–2 ms per 512-sample (32 ms at 16 kHz) chunk on CPU.
/// This is negligible relative to audio I/O round-trip latency.
///
/// # Silero VAD v4 I/O contract
/// - Input  `input`:  `[1, 1, chunk_len]` f32
/// - Input  `h`:      `[2, 1, 64]`        f32  (recurrent state)
/// - Input  `c`:      `[2, 1, 64]`        f32  (recurrent state)
/// - Input  `sr`:     `[1]`               i64  (sample rate)
/// - Output `output`: `[1, 1]`            f32  (speech probability)
/// - Output `hn`:     `[2, 1, 64]`        f32  (updated h)
/// - Output `cn`:     `[2, 1, 64]`        f32  (updated c)
#[cfg(feature = "silero")]
pub struct SileroVad {
    session: ort::Session,
    threshold: f32,
    state_h: ndarray::Array3<f32>,
    state_c: ndarray::Array3<f32>,
    sample_rate: i64,
}

#[cfg(feature = "silero")]
impl SileroVad {
    const STATE_DIM: usize = 64;

    /// Create a new Silero VAD instance.
    ///
    /// `model_path` — path to `silero_vad.onnx` (v4).
    /// `threshold`  — P(speech) threshold; 0.5 is the recommended default.
    /// `sample_rate` — expected audio sample rate in Hz (8000 or 16000).
    pub fn new(model_path: &str, threshold: f32, sample_rate: u32) -> anyhow::Result<Self> {
        let session = ort::Session::builder()?
            .with_optimization_level(ort::GraphOptimizationLevel::Level3)?
            .with_intra_threads(1)?
            .commit_from_file(model_path)?;

        // Silero VAD v4 state shape: [2, 1, 64]
        let state_h = ndarray::Array3::<f32>::zeros((2, 1, Self::STATE_DIM));
        let state_c = ndarray::Array3::<f32>::zeros((2, 1, Self::STATE_DIM));

        Ok(Self {
            session,
            threshold,
            state_h,
            state_c,
            sample_rate: sample_rate as i64,
        })
    }

    /// Reset the internal recurrent state.
    ///
    /// Call this between utterances (i.e., whenever a new hold-to-talk
    /// session begins) to prevent cross-utterance state leakage.
    pub fn reset(&mut self) {
        self.state_h.fill(0.0);
        self.state_c.fill(0.0);
    }

    /// Process one audio chunk and return the speech probability [0.0, 1.0].
    ///
    /// `chunk` must be a contiguous slice of f32 PCM samples at the sample
    /// rate specified in [`SileroVad::new`].  The recommended chunk length
    /// for 16 kHz audio is 512 samples (32 ms).
    ///
    /// The internal recurrent state is updated in place.
    pub fn process(&mut self, chunk: &[f32]) -> anyhow::Result<f32> {
        use ort::inputs;

        let chunk_len = chunk.len();

        // Shape: [1, 1, chunk_len]
        let audio = ndarray::Array3::from_shape_vec((1, 1, chunk_len), chunk.to_vec())
            .map_err(|e| anyhow::anyhow!("building audio array: {e}"))?;

        // sr: [1]
        let sr_array = ndarray::arr1(&[self.sample_rate]);

        let outputs = self.session.run(
            inputs![
                "input" => audio.view(),
                "h"     => self.state_h.view(),
                "c"     => self.state_c.view(),
                "sr"    => sr_array.view(),
            ]
            .map_err(|e| anyhow::anyhow!("building ONNX inputs: {e}"))?,
        )?;

        // Output 0: speech probability [1, 1]
        let prob_tensor = outputs[0]
            .try_extract_tensor::<f32>()
            .map_err(|e| anyhow::anyhow!("extracting speech prob: {e}"))?;
        let speech_prob = prob_tensor.view()[[0, 0]];

        // Output 1: updated h [2, 1, 64]
        let h_tensor = outputs[1]
            .try_extract_tensor::<f32>()
            .map_err(|e| anyhow::anyhow!("extracting h state: {e}"))?;
        self.state_h.assign(
            &h_tensor
                .view()
                .into_shape_with_order((2, 1, Self::STATE_DIM))
                .map_err(|e| anyhow::anyhow!("reshaping h state: {e}"))?,
        );

        // Output 2: updated c [2, 1, 64]
        let c_tensor = outputs[2]
            .try_extract_tensor::<f32>()
            .map_err(|e| anyhow::anyhow!("extracting c state: {e}"))?;
        self.state_c.assign(
            &c_tensor
                .view()
                .into_shape_with_order((2, 1, Self::STATE_DIM))
                .map_err(|e| anyhow::anyhow!("reshaping c state: {e}"))?,
        );

        Ok(speech_prob)
    }

    /// Return `true` if the chunk contains speech (P(speech) ≥ threshold).
    pub fn is_speech(&mut self, chunk: &[f32]) -> anyhow::Result<bool> {
        Ok(self.process(chunk)? >= self.threshold)
    }
}
