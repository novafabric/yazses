use serde::{Deserialize, Serialize};

/// A single chat message.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Message {
    pub role: Role,
    pub content: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Role {
    System,
    User,
    Assistant,
    Tool,
}

/// What the model decided to do — emit text OR call a tool.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum LLMOutput {
    /// Plain dictated text to be injected by the `type_text` implicit path.
    Text(String),
    /// A single structured tool invocation (grammar-constrained decoding
    /// guarantees 100% syntactic validity — adr-004, CI non-negotiable).
    ToolCall(ToolCall),
}

/// A single tool invocation returned by the LLM.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolCall {
    pub tool: String,
    pub arguments: serde_json::Value,
}

/// Two-tier LLM routing (adr-003, FR-19). v1.0 ships Fast only;
/// Deep is reserved for v2 and returns an error if requested.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub enum Tier {
    #[default]
    Fast,
    Deep,
}

/// Everything needed for a single LLM turn.
#[derive(Debug, Clone)]
pub struct LLMRequest {
    pub system_prompt: String,
    pub messages: Vec<Message>,
    /// GBNF grammar string for grammar-constrained decoding.
    /// Produced by `ToolRegistry::grammar()` at startup; `None` for free text.
    pub grammar: Option<String>,
    /// LSP editor context block prepended to the prompt when non-empty.
    /// Must be `<= 2 000` BPE tokens to stay within the latency budget.
    pub editor_context: Option<String>,
    pub max_tokens: u32,
    pub temperature: f32,
    /// Routing tier (FR-19). v1.0 only supports `Fast`; `Deep` returns an error.
    pub tier: Tier,
}

impl LLMRequest {
    pub fn builder(system_prompt: impl Into<String>) -> LLMRequestBuilder {
        LLMRequestBuilder::new(system_prompt.into())
    }
}

pub struct LLMRequestBuilder {
    inner: LLMRequest,
}

impl LLMRequestBuilder {
    fn new(system_prompt: String) -> Self {
        Self {
            inner: LLMRequest {
                system_prompt,
                messages: Vec::new(),
                grammar: None,
                editor_context: None,
                max_tokens: 256,
                temperature: 0.0,
                tier: Tier::Fast,
            },
        }
    }

    pub fn message(mut self, role: Role, content: impl Into<String>) -> Self {
        self.inner.messages.push(Message {
            role,
            content: content.into(),
        });
        self
    }

    pub fn grammar(mut self, gbnf: impl Into<String>) -> Self {
        self.inner.grammar = Some(gbnf.into());
        self
    }

    pub fn editor_context(mut self, ctx: impl Into<String>) -> Self {
        self.inner.editor_context = Some(ctx.into());
        self
    }

    pub fn max_tokens(mut self, n: u32) -> Self {
        self.inner.max_tokens = n;
        self
    }

    pub fn temperature(mut self, t: f32) -> Self {
        self.inner.temperature = t;
        self
    }

    pub fn tier(mut self, tier: Tier) -> Self {
        self.inner.tier = tier;
        self
    }

    pub fn build(self) -> LLMRequest {
        self.inner
    }
}

/// Uniform interface for all LLM backends (adr-003).
#[async_trait::async_trait]
pub trait LLMBackend: Send + Sync {
    fn name(&self) -> &str;
    async fn complete(&self, request: LLMRequest) -> anyhow::Result<LLMOutput>;
}
