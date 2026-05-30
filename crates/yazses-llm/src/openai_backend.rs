use crate::protocol::{LLMBackend, LLMOutput, LLMRequest, Tier};

/// OpenAI-compatible cloud backend — opt-in only (adr-011, S-06).
///
/// Requires explicit user config in `~/.config/yazses/cloud.toml`.
/// **Feature gate:** `--features openai-compatible` (pulls in reqwest).
/// Never used in default config — zero-egress non-negotiable (NFR-SEC03).
pub struct OpenAICompatibleBackend {
    #[allow(dead_code)]
    base_url: String,
    #[allow(dead_code)]
    model: String,
    #[allow(dead_code)]
    api_key: String,
    #[cfg(feature = "openai-compatible")]
    client: reqwest::Client,
}

impl OpenAICompatibleBackend {
    pub fn new(
        base_url: impl Into<String>,
        model: impl Into<String>,
        api_key: impl Into<String>,
    ) -> anyhow::Result<Self> {
        let base_url = base_url.into();
        let model = model.into();
        let api_key = api_key.into();
        #[cfg(feature = "openai-compatible")]
        {
            use tracing::info;
            let client = reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(120))
                .build()?;
            info!(%base_url, %model, "OpenAI-compatible cloud backend initialised (opt-in)");
            Ok(Self { base_url, model, api_key, client })
        }
        #[cfg(not(feature = "openai-compatible"))]
        {
            let _ = (base_url, model, api_key);
            anyhow::bail!(
                "OpenAICompatibleBackend requires `--features openai-compatible`"
            )
        }
    }
}

#[async_trait::async_trait]
impl LLMBackend for OpenAICompatibleBackend {
    fn name(&self) -> &str {
        "openai-compatible"
    }

    async fn complete(&self, request: LLMRequest) -> anyhow::Result<LLMOutput> {
        if request.tier == Tier::Deep {
            anyhow::bail!("deep-tier routing reserved for v2");
        }
        #[cfg(feature = "openai-compatible")]
        {
            complete_openai(
                &self.client,
                &self.base_url,
                &self.model,
                &self.api_key,
                request,
            )
            .await
        }
        #[cfg(not(feature = "openai-compatible"))]
        {
            let _ = request;
            anyhow::bail!("OpenAICompatibleBackend not compiled in")
        }
    }
}

#[cfg(feature = "openai-compatible")]
async fn complete_openai(
    client: &reqwest::Client,
    base_url: &str,
    model: &str,
    api_key: &str,
    request: LLMRequest,
) -> anyhow::Result<LLMOutput> {
    use crate::protocol::{Role, ToolCall};
    use tracing::debug;

    let mut msgs = vec![serde_json::json!({"role": "system", "content": request.system_prompt})];
    if let Some(ctx) = &request.editor_context {
        // Inject editor context into the last user message or as a separate system turn.
        msgs.push(serde_json::json!({"role": "system", "content": format!("<editor_context>\n{ctx}\n</editor_context>")}));
    }
    for msg in &request.messages {
        let role = match msg.role {
            Role::User => "user",
            Role::Assistant => "assistant",
            Role::Tool => "tool",
            Role::System => "system",
        };
        msgs.push(serde_json::json!({"role": role, "content": msg.content}));
    }

    let body = serde_json::json!({
        "model": model,
        "messages": msgs,
        "max_tokens": request.max_tokens,
        "temperature": request.temperature,
    });

    let url = format!("{base_url}/v1/chat/completions");
    debug!(%url, %model, "OpenAI-compatible request");

    let resp: serde_json::Value = client
        .post(&url)
        .bearer_auth(api_key)
        .json(&body)
        .send()
        .await
        .map_err(|e| anyhow::anyhow!("OpenAI HTTP error: {e}"))?
        .json()
        .await
        .map_err(|e| anyhow::anyhow!("OpenAI response parse: {e}"))?;

    // Handle native tool_calls.
    if let Some(calls) = resp["choices"][0]["message"]["tool_calls"].as_array() {
        if let Some(first) = calls.first() {
            let tool = first["function"]["name"]
                .as_str()
                .unwrap_or("cancel_request")
                .to_string();
            let arguments = first["function"]["arguments"].clone();
            return Ok(LLMOutput::ToolCall(ToolCall { tool, arguments }));
        }
    }

    let content = resp["choices"][0]["message"]["content"]
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("OpenAI response: no content\nraw: {resp}"))?
        .trim()
        .to_string();

    // Parse JSON tool call if content starts with '{'.
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
