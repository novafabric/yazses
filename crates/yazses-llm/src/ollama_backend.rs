use crate::protocol::{LLMBackend, LLMOutput, LLMRequest};

/// Ollama HTTP backend — for users who already run the Ollama daemon (adr-003).
///
/// **Feature gate:** `--features ollama` (pulls in `reqwest`).
/// Connects to the Ollama HTTP API at `OLLAMA_HOST` env or `127.0.0.1:11434`.
/// Grammar-constrained decoding is not available on the Ollama path; v1.0 uses
/// JSON mode instead.
pub struct OllamaBackend {
    #[allow(dead_code)]
    base_url: String,
    #[allow(dead_code)]
    model: String,
    #[cfg(feature = "ollama")]
    client: reqwest::Client,
}

impl OllamaBackend {
    pub fn new(model: impl Into<String>) -> anyhow::Result<Self> {
        let model = model.into();
        let base_url =
            std::env::var("OLLAMA_HOST").unwrap_or_else(|_| "http://127.0.0.1:11434".into());

        #[cfg(feature = "ollama")]
        {
            use tracing::info;
            let client = reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(120))
                .build()?;
            info!(%base_url, %model, "Ollama backend initialised");
            Ok(Self {
                base_url,
                model,
                client,
            })
        }
        #[cfg(not(feature = "ollama"))]
        {
            let _ = base_url;
            anyhow::bail!(
                "OllamaBackend requires the `ollama` feature; \
                 rebuild with `--features ollama`. (model={model})"
            )
        }
    }
}

#[async_trait::async_trait]
impl LLMBackend for OllamaBackend {
    fn name(&self) -> &str {
        "ollama"
    }

    async fn complete(&self, request: LLMRequest) -> anyhow::Result<LLMOutput> {
        if request.tier == crate::protocol::Tier::Deep {
            anyhow::bail!("two-tier deep routing is reserved for v2; use Tier::Fast");
        }
        #[cfg(feature = "ollama")]
        {
            complete_ollama(&self.client, &self.base_url, &self.model, request).await
        }
        #[cfg(not(feature = "ollama"))]
        {
            let _ = request;
            anyhow::bail!("OllamaBackend not compiled in (missing `ollama` feature)")
        }
    }
}

// ── reqwest implementation ────────────────────────────────────────────────────

#[cfg(feature = "ollama")]
async fn complete_ollama(
    client: &reqwest::Client,
    base_url: &str,
    model: &str,
    request: LLMRequest,
) -> anyhow::Result<LLMOutput> {
    use crate::protocol::ToolCall;
    use tracing::debug;
    let messages = build_ollama_messages(&request);
    // No "format":"json" — rely on system prompt instructions.
    // format:json with Cursor's embedded Ollama causes null message.content
    // when the model uses native tool_calls rather than JSON-in-content.
    let body = serde_json::json!({
        "model": model,
        "messages": messages,
        "stream": false,
        "options": {
            "num_predict": request.max_tokens,
            "temperature": request.temperature,
        },
    });

    let url = format!("{base_url}/api/chat");
    debug!(%url, %model, "Ollama request");

    let resp: serde_json::Value = client
        .post(&url)
        .json(&body)
        .send()
        .await
        .map_err(|e| anyhow::anyhow!("Ollama HTTP error: {e}"))?
        .json()
        .await
        .map_err(|e| anyhow::anyhow!("Ollama response parse error: {e}"))?;

    debug!(resp = %resp, "Ollama raw response");

    // Handle Ollama native tool_calls (content is null, tool_calls array present).
    if resp["message"]["content"].is_null() {
        if let Some(calls) = resp["message"]["tool_calls"].as_array() {
            if let Some(first) = calls.first() {
                let tool = first["function"]["name"]
                    .as_str()
                    .unwrap_or("cancel_request")
                    .to_string();
                let arguments = first["function"]["arguments"].clone();
                return Ok(LLMOutput::ToolCall(ToolCall { tool, arguments }));
            }
        }
        anyhow::bail!("Ollama response: message.content is null and no tool_calls present\nraw: {resp}");
    }

    let content = resp["message"]["content"]
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("Ollama response: message.content is not a string\nraw: {resp}"))?
        .trim()
        .to_string();

    // Try to parse as a JSON tool call (YazSes format: {"tool":"..","arguments":{..}}).
    if content.starts_with('{') {
        if let Ok(v) = serde_json::from_str::<serde_json::Value>(&content) {
            if let Some(tool) = v.get("tool").and_then(|t| t.as_str()) {
                let arguments = v.get("arguments").cloned().unwrap_or_default();
                return Ok(LLMOutput::ToolCall(ToolCall {
                    tool: tool.into(),
                    arguments,
                }));
            }
        }
    }
    Ok(LLMOutput::Text(content))
}

#[cfg(feature = "ollama")]
fn build_ollama_messages(request: &LLMRequest) -> Vec<serde_json::Value> {
    use crate::protocol::Role;
    let mut system = request.system_prompt.clone();
    if let Some(ctx) = &request.editor_context {
        system.push_str("\n\n<editor_context>\n");
        system.push_str(ctx);
        system.push_str("\n</editor_context>");
    }
    let mut msgs = vec![serde_json::json!({"role": "system", "content": system})];
    for msg in &request.messages {
        let role = match msg.role {
            Role::User => "user",
            Role::Assistant => "assistant",
            Role::Tool => "tool",
            Role::System => "system",
        };
        msgs.push(serde_json::json!({"role": role, "content": msg.content}));
    }
    msgs
}
