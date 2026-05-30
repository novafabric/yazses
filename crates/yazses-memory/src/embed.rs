/// Embedding backend abstraction for personal-memory vector indexing (adr-007).
///
/// Default model: BGE-small-en (384-dim).  The ONNX path is feature-gated
/// (`--features onnx`); the `MockEmbedder` is always available for tests.
#[async_trait::async_trait]
pub trait EmbeddingBackend: Send + Sync {
    fn dimensions(&self) -> usize;
    /// Compute a normalised float vector for `text`.
    fn embed(&self, text: &str) -> anyhow::Result<Vec<f32>>;
}

// ── MockEmbedder ──────────────────────────────────────────────────────────────

/// Deterministic unit-vector embedder for unit tests.
///
/// Maps text → a 384-dim vector where only the component at index
/// `(first_byte % 384)` is 1.0, all others 0.0.  Two texts with the same
/// first byte are identical; otherwise orthogonal.  This gives predictable
/// KNN distances without any ML dependency.
pub struct MockEmbedder;

impl EmbeddingBackend for MockEmbedder {
    fn dimensions(&self) -> usize {
        384
    }

    fn embed(&self, text: &str) -> anyhow::Result<Vec<f32>> {
        let mut v = vec![0.0f32; 384];
        if let Some(&b) = text.as_bytes().first() {
            v[(b as usize) % 384] = 1.0;
        }
        Ok(v)
    }
}

// ── OnnxEmbedder (feature-gated) ─────────────────────────────────────────────

/// BGE-small-en ONNX embedder using ONNX Runtime.
///
/// **Feature gate:** `--features onnx`
/// Requires `libonnxruntime.so` / `onnxruntime.dll` on `ORT_DYLIB_PATH` or
/// the system library path at runtime.
///
/// Constructs via [`OnnxEmbedder::new`] with a path to both the ONNX model
/// file and the accompanying tokenizer JSON (HuggingFace format).
/// Mean-pools the last hidden state over non-padding tokens, then L2-normalises
/// the result to produce a unit vector suitable for cosine KNN.
#[cfg(feature = "onnx")]
pub struct OnnxEmbedder {
    session: ort::Session,
    tokenizer: tokenizers::Tokenizer,
    dimensions: usize,
}

#[cfg(feature = "onnx")]
impl OnnxEmbedder {
    /// Create a new embedder.
    ///
    /// `model_path`     — path to the BGE-small-en ONNX model file.
    /// `tokenizer_path` — path to the HuggingFace `tokenizer.json` file.
    pub fn new(model_path: &str, tokenizer_path: &str) -> anyhow::Result<Self> {
        let session = ort::Session::builder()?
            .with_optimization_level(ort::GraphOptimizationLevel::Level3)?
            .with_intra_threads(1)?
            .commit_from_file(model_path)?;

        // BGE-small-en produces 384-dim; BGE-base produces 768-dim.
        // Default to 384; callers that use a different model should override
        // by reading the output shape.  For BGE-small-en this is always 384.
        let dimensions = 384usize;

        let tokenizer = tokenizers::Tokenizer::from_file(tokenizer_path)
            .map_err(|e| anyhow::anyhow!("loading tokenizer from {tokenizer_path}: {e}"))?;

        Ok(Self {
            session,
            tokenizer,
            dimensions,
        })
    }
}

#[cfg(feature = "onnx")]
impl EmbeddingBackend for OnnxEmbedder {
    fn dimensions(&self) -> usize {
        self.dimensions
    }

    fn embed(&self, text: &str) -> anyhow::Result<Vec<f32>> {
        use ort::inputs;

        // ── Tokenise ──────────────────────────────────────────────────────────
        let encoding = self
            .tokenizer
            .encode(text, true)
            .map_err(|e| anyhow::anyhow!("tokenizing '{text}': {e}"))?;

        let input_ids: Vec<i64> = encoding.get_ids().iter().map(|&id| id as i64).collect();
        let attention_mask: Vec<i64> = encoding
            .get_attention_mask()
            .iter()
            .map(|&m| m as i64)
            .collect();
        let token_type_ids: Vec<i64> = vec![0i64; input_ids.len()];

        let seq_len = input_ids.len();

        // ── Build [1, seq_len] tensors ────────────────────────────────────────
        let input_ids_array =
            ndarray::Array2::from_shape_vec((1, seq_len), input_ids)
                .map_err(|e| anyhow::anyhow!("building input_ids array: {e}"))?;
        let attention_mask_array =
            ndarray::Array2::from_shape_vec((1, seq_len), attention_mask)
                .map_err(|e| anyhow::anyhow!("building attention_mask array: {e}"))?;
        let token_type_ids_array =
            ndarray::Array2::from_shape_vec((1, seq_len), token_type_ids)
                .map_err(|e| anyhow::anyhow!("building token_type_ids array: {e}"))?;

        // ── Run inference ─────────────────────────────────────────────────────
        let outputs = self.session.run(
            inputs![
                "input_ids"      => input_ids_array.view(),
                "attention_mask" => attention_mask_array.view(),
                "token_type_ids" => token_type_ids_array.view(),
            ]
            .map_err(|e| anyhow::anyhow!("building ONNX inputs: {e}"))?,
        )?;

        // ── Mean-pool last_hidden_state [1, seq_len, hidden_dim] ──────────────
        let hidden = outputs[0]
            .try_extract_tensor::<f32>()
            .map_err(|e| anyhow::anyhow!("extracting tensor: {e}"))?;
        let hidden = hidden.view();
        // hidden shape: [1, seq_len, hidden_dim]
        let hidden_dim = hidden.shape()[2];
        let mut pooled = vec![0.0f32; hidden_dim];
        let mut count = 0.0f32;
        let attn = encoding.get_attention_mask();
        for s in 0..seq_len {
            if attn[s] == 1 {
                for d in 0..hidden_dim {
                    pooled[d] += hidden[[0, s, d]];
                }
                count += 1.0;
            }
        }
        if count > 0.0 {
            for v in pooled.iter_mut() {
                *v /= count;
            }
        }

        // ── L2-normalise ──────────────────────────────────────────────────────
        let norm: f32 = pooled.iter().map(|x| x * x).sum::<f32>().sqrt();
        if norm > 1e-9 {
            for v in pooled.iter_mut() {
                *v /= norm;
            }
        }

        Ok(pooled)
    }
}
