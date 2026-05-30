use crate::protocol::{LLMBackend, LLMOutput, LLMRequest};

/// Deterministic LLM backend for unit tests.
pub struct MockLLMBackend {
    output: LLMOutput,
}

impl MockLLMBackend {
    pub fn text(response: impl Into<String>) -> Self {
        Self {
            output: LLMOutput::Text(response.into()),
        }
    }

    pub fn tool_call(tool: impl Into<String>, arguments: serde_json::Value) -> Self {
        Self {
            output: LLMOutput::ToolCall(crate::protocol::ToolCall {
                tool: tool.into(),
                arguments,
            }),
        }
    }
}

#[async_trait::async_trait]
impl LLMBackend for MockLLMBackend {
    fn name(&self) -> &str {
        "mock"
    }

    async fn complete(&self, _request: LLMRequest) -> anyhow::Result<LLMOutput> {
        Ok(self.output.clone())
    }
}
