use crate::protocol::{LLMBackend, LLMOutput, LLMRequest};

/// llama.cpp LLM backend — default on Linux, macOS Intel, and Windows (adr-003).
///
/// **Feature gate:** `--features llama-cpp` (requires cmake + C++ at build time).
/// Model files must be GGUF format; download via `yazses model pull`.
///
/// **Prompt caching is mandatory** for NFR-P01 when LSP editor context is
/// active: without it, a 2 000-token EditorContext prefix re-encodes on every
/// turn (~1 333 ms), blowing the 1-second budget. [EVIDENCE
/// spikes/s3-llm-default/report.md §Latency]
///
/// Default model: **Qwen3-7B-Instruct Q4_K_M** (~5.2 GB). English + Persian.
/// [EVIDENCE spikes/s3-llm-default/report.md — OQ-02 and OQ-03 both SETTLED]
pub struct LlamaCppBackend {
    #[allow(dead_code)]
    model_path: String,
    #[cfg(feature = "llama-cpp")]
    model: llama_cpp_2::model::LlamaModel,
}

impl LlamaCppBackend {
    /// Load a GGUF model file.
    ///
    /// `model_path`: path to a `.gguf` file, e.g.
    /// `~/.local/share/yazses/models/qwen3-7b-instruct-q4_k_m.gguf`
    pub fn new(model_path: impl Into<String>) -> anyhow::Result<Self> {
        let model_path = model_path.into();
        #[cfg(feature = "llama-cpp")]
        {
            load_llama_model(&model_path).map(|model| Self { model_path, model })
        }
        #[cfg(not(feature = "llama-cpp"))]
        {
            anyhow::bail!(
                "LlamaCppBackend requires the `llama-cpp` feature; \
                 rebuild with `--features llama-cpp` (requires cmake + C++ compiler). \
                 (model_path={model_path})"
            )
        }
    }
}

#[async_trait::async_trait]
impl LLMBackend for LlamaCppBackend {
    fn name(&self) -> &str {
        "llama-cpp"
    }

    async fn complete(&self, request: LLMRequest) -> anyhow::Result<LLMOutput> {
        if request.tier == crate::protocol::Tier::Deep {
            anyhow::bail!("two-tier deep routing is reserved for v2; use Tier::Fast");
        }
        #[cfg(feature = "llama-cpp")]
        {
            complete_llama(&self.model, request)
        }
        #[cfg(not(feature = "llama-cpp"))]
        {
            let _ = request;
            anyhow::bail!("LlamaCppBackend not compiled in (missing `llama-cpp` feature)")
        }
    }
}

// ── llama-cpp-2 implementation ────────────────────────────────────────────────

#[cfg(feature = "llama-cpp")]
fn load_llama_model(model_path: &str) -> anyhow::Result<llama_cpp_2::model::LlamaModel> {
    use tracing::info;
    info!(%model_path, "loading llama.cpp model");
    let backend = llama_cpp_2::llama_backend::LlamaBackend::init()?;
    let params = llama_cpp_2::model::params::LlamaModelParams::default();
    let model = llama_cpp_2::model::LlamaModel::load_from_file(&backend, model_path, &params)
        .map_err(|e| anyhow::anyhow!("loading model {model_path}: {e}"))?;
    info!(%model_path, "llama.cpp model loaded");
    Ok(model)
}

#[cfg(feature = "llama-cpp")]
fn complete_llama(
    model: &llama_cpp_2::model::LlamaModel,
    request: LLMRequest,
) -> anyhow::Result<LLMOutput> {
    use llama_cpp_2::context::params::LlamaContextParams;
    use llama_cpp_2::llama_batch::LlamaBatch;
    use llama_cpp_2::token::data_array::LlamaTokenDataArray;

    // Build prompt string from messages.
    let prompt = format_chat_prompt(&request);

    let ctx_params =
        LlamaContextParams::default().with_n_ctx(std::num::NonZeroU32::new(4096).unwrap());

    let mut ctx = model.new_context(
        &llama_cpp_2::llama_backend::LlamaBackend::init()?,
        ctx_params,
    )?;

    let tokens = model.str_to_token(&prompt, llama_cpp_2::model::AddBos::Always)?;
    let mut batch = LlamaBatch::new(512, 1);
    let last = tokens.len() - 1;
    for (i, tok) in tokens.iter().enumerate() {
        batch.add(*tok, i as i32, &[0], i == last)?;
    }
    ctx.decode(&mut batch)?;

    let mut output = String::new();
    for _ in 0..request.max_tokens {
        let candidates = ctx.candidates_ith(batch.n_tokens() - 1);
        let mut arr = LlamaTokenDataArray::from_iter(candidates, false);

        if let Some(grammar_str) = &request.grammar {
            // Grammar-constrained sampling is applied externally in production;
            // for the scaffold we sample greedily and document where grammar
            // integration hooks in.
            let _ = grammar_str;
        }

        ctx.sample_temp(&mut arr, request.temperature);
        ctx.sample_softmax(&mut arr);
        let tok = arr.data[0].id();

        if tok == model.token_eos() {
            break;
        }
        output.push_str(&model.token_to_str(tok, llama_cpp_2::model::Special::Tokenize)?);
        batch = LlamaBatch::new(1, 1);
        batch.add(tok, tokens.len() as i32, &[0], true)?;
        ctx.decode(&mut batch)?;
    }

    // Try to parse as a tool call first; fall back to text.
    let trimmed = output.trim().to_string();
    if trimmed.starts_with('{') {
        if let Ok(call) = serde_json::from_str::<serde_json::Value>(&trimmed) {
            if call.get("tool").is_some() {
                let tool = call["tool"].as_str().unwrap_or("").to_string();
                let arguments = call.get("arguments").cloned().unwrap_or_default();
                return Ok(LLMOutput::ToolCall(crate::protocol::ToolCall {
                    tool,
                    arguments,
                }));
            }
        }
    }
    Ok(LLMOutput::Text(trimmed))
}

#[cfg(feature = "llama-cpp")]
fn format_chat_prompt(request: &LLMRequest) -> String {
    use crate::protocol::Role;
    let mut prompt = String::new();
    prompt.push_str("<|system|>\n");
    prompt.push_str(&request.system_prompt);
    if let Some(ctx) = &request.editor_context {
        prompt.push_str("\n\n<editor_context>\n");
        prompt.push_str(ctx);
        prompt.push_str("\n</editor_context>");
    }
    prompt.push_str("\n<|end|>\n");
    for msg in &request.messages {
        match msg.role {
            Role::User => {
                prompt.push_str("<|user|>\n");
                prompt.push_str(&msg.content);
                prompt.push_str("\n<|end|>\n");
            }
            Role::Assistant => {
                prompt.push_str("<|assistant|>\n");
                prompt.push_str(&msg.content);
                prompt.push_str("\n<|end|>\n");
            }
            _ => {}
        }
    }
    prompt.push_str("<|assistant|>\n");
    prompt
}
