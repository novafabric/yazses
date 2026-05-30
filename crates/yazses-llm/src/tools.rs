use serde_json::json;

use crate::protocol::ToolCall;

/// Compile-time description of one tool the LLM may invoke.
#[derive(Debug, Clone)]
pub struct ToolDefinition {
    /// Must match the grammar-constrained tool name exactly.
    pub name: &'static str,
    pub description: &'static str,
    /// JSON Schema `object` describing the `arguments` map.
    pub parameters: serde_json::Value,
}

/// All v1.0 tools (≤ 20 per build prompt §4 Phase 3).
///
/// Most-common tools are listed first so the GBNF sampler benefits from
/// shorter prefixes on the hot path.
pub fn default_tools() -> Vec<ToolDefinition> {
    vec![
        ToolDefinition {
            name: "type_text",
            description: "Inject the given text into the focused application as keyboard events.",
            parameters: json!({"type":"object","required":["text"],"properties":{"text":{"type":"string","description":"Text to inject"}}}),
        },
        ToolDefinition {
            name: "key_sequence",
            description: "Send a key sequence, e.g. ctrl+s, Escape, Return.",
            parameters: json!({"type":"object","required":["keys"],"properties":{"keys":{"type":"string","description":"Key combo, e.g. \"ctrl+s\""}}}),
        },
        ToolDefinition {
            name: "commit_to_memory",
            description: "Store a fact or note in the personal memory store.",
            parameters: json!({"type":"object","required":["content"],"properties":{"content":{"type":"string","description":"The memory text to store"}}}),
        },
        ToolDefinition {
            name: "forget_last",
            description: "Remove the most recently committed memory entry.",
            parameters: json!({"type":"object","properties":{}}),
        },
        ToolDefinition {
            name: "recall",
            description: "Retrieve memories relevant to a query.",
            parameters: json!({"type":"object","required":["query"],"properties":{"query":{"type":"string","description":"Semantic search query"}}}),
        },
        ToolDefinition {
            name: "clarify",
            description: "Ask the user a clarifying question via a TTS announcement.",
            parameters: json!({"type":"object","required":["question"],"properties":{"question":{"type":"string","description":"The question to speak aloud"}}}),
        },
        ToolDefinition {
            name: "open_file",
            description: "Open a file by path in the current editor or default application.",
            parameters: json!({"type":"object","required":["path"],"properties":{"path":{"type":"string","description":"Absolute or relative file path"}}}),
        },
        ToolDefinition {
            name: "goto_symbol",
            description: "Jump to a symbol in the active editor via LSP workspaceSymbol.",
            parameters: json!({"type":"object","required":["symbol"],"properties":{"symbol":{"type":"string","description":"Symbol name or pattern"}}}),
        },
        ToolDefinition {
            name: "git_commit",
            description: "Stage all changes and create a git commit with the given message.",
            parameters: json!({"type":"object","required":["message"],"properties":{"message":{"type":"string","description":"Commit message"}}}),
        },
        ToolDefinition {
            name: "send_message",
            description: "Send a message via a configured messaging integration.",
            parameters: json!({"type":"object","required":["recipient","body"],"properties":{"recipient":{"type":"string","description":"Channel, user, or address"},"body":{"type":"string","description":"Message body"}}}),
        },
        ToolDefinition {
            name: "app_launch",
            description: "Launch an application by name or bundle ID.",
            parameters: json!({"type":"object","required":["app"],"properties":{"app":{"type":"string","description":"Application name or bundle ID"}}}),
        },
        ToolDefinition {
            name: "window_focus",
            description: "Bring a window matching the given title or app name to the foreground.",
            parameters: json!({"type":"object","required":["target"],"properties":{"target":{"type":"string","description":"Window title or app name"}}}),
        },
        ToolDefinition {
            name: "volume_set",
            description: "Set the system audio output volume (0–100).",
            parameters: json!({"type":"object","required":["level"],"properties":{"level":{"type":"number","description":"Volume level 0–100"}}}),
        },
        ToolDefinition {
            name: "media_play_pause",
            description: "Toggle media playback (play/pause).",
            parameters: json!({"type":"object","properties":{}}),
        },
        ToolDefinition {
            name: "screenshot_named",
            description: "Take a screenshot and save it with the given filename.",
            parameters: json!({"type":"object","required":["name"],"properties":{"name":{"type":"string","description":"Base filename without extension"}}}),
        },
        ToolDefinition {
            name: "note_quick",
            description: "Append a quick note to the daily note file.",
            parameters: json!({"type":"object","required":["text"],"properties":{"text":{"type":"string","description":"Note content"}}}),
        },
        ToolDefinition {
            name: "time_set_timer",
            description: "Set a countdown timer for the given number of minutes.",
            parameters: json!({"type":"object","required":["minutes"],"properties":{"minutes":{"type":"number","description":"Duration in minutes"}}}),
        },
        ToolDefinition {
            name: "dismiss_notification",
            description: "Dismiss the most recent system notification.",
            parameters: json!({"type":"object","properties":{}}),
        },
        ToolDefinition {
            name: "cancel_request",
            description: "Cancel the current pipeline action (recording or LLM generation).",
            parameters: json!({"type":"object","properties":{}}),
        },
        ToolDefinition {
            name: "mode_switch",
            description: "Switch YazSes operating mode (e.g. dictate, command, coding).",
            parameters: json!({"type":"object","required":["mode"],"properties":{"mode":{"type":"string","description":"Target mode name"}}}),
        },
    ]
}

/// Registry of tools with a compiled GBNF grammar for constrained decoding.
///
/// The grammar is built once at startup and cached. Every tool call the LLM
/// emits is guaranteed syntactically valid — this is the CI non-negotiable
/// from the build prompt §6 point 3 (tool-call syntactic validity = 100%).
pub struct ToolRegistry {
    tools: Vec<ToolDefinition>,
    grammar: String,
}

impl ToolRegistry {
    /// Build the default v1.0 registry and compile its GBNF grammar.
    pub fn default_v1() -> Self {
        let tools = default_tools();
        let grammar = build_gbnf_grammar(&tools);
        Self { tools, grammar }
    }

    pub fn tools(&self) -> &[ToolDefinition] {
        &self.tools
    }

    /// GBNF grammar string for llama.cpp grammar-constrained decoding (adr-004).
    ///
    /// Constrains the model to emit:
    /// ```json
    /// {"tool": "<registered-name>", "arguments": {...}}
    /// ```
    /// The `tool` field is strictly one of the registered names — hallucinated
    /// tool names are structurally impossible.
    pub fn grammar(&self) -> &str {
        &self.grammar
    }

    /// Parse a raw JSON string emitted by the LLM into a `ToolCall`.
    ///
    /// Returns an error when the JSON is malformed or the tool name is not
    /// registered. With grammar-constrained decoding this should never fail
    /// in production; the test suite covers it explicitly.
    pub fn parse_call(&self, raw: &str) -> anyhow::Result<ToolCall> {
        let v: serde_json::Value = serde_json::from_str(raw)
            .map_err(|e| anyhow::anyhow!("tool-call JSON parse error: {e}\nraw={raw:?}"))?;
        let tool = v
            .get("tool")
            .and_then(|t| t.as_str())
            .ok_or_else(|| anyhow::anyhow!("tool-call missing `tool` field"))?;
        if !self.tools.iter().any(|t| t.name == tool) {
            anyhow::bail!("unknown tool `{tool}`");
        }
        let arguments = v
            .get("arguments")
            .cloned()
            .unwrap_or(serde_json::Value::Object(Default::default()));
        Ok(ToolCall {
            tool: tool.into(),
            arguments,
        })
    }
}

// ── GBNF grammar compiler ─────────────────────────────────────────────────────

/// Compile a GBNF grammar from the registered tool definitions.
///
/// The grammar enforces:
/// 1. `tool` is one of the registered names.
/// 2. `arguments` is any valid JSON object.
///
/// Per-argument schema validation (JSON-Schema → GBNF per-field) is a future
/// enhancement; v1.0 trusts the model's in-context learning from tool descriptions.
pub fn build_gbnf_grammar(tools: &[ToolDefinition]) -> String {
    let names: Vec<String> = tools
        .iter()
        .map(|t| format!("\"\\\"{}\\\"\"", t.name))
        .collect();
    let tool_names = names.join(" | ");

    format!(
        concat!(
            "root       ::= tool-call\n",
            "tool-call  ::= \"{{\" ws \"\\\"tool\\\"\" ws \":\" ws tool-name ws \",\" ws \"\\\"arguments\\\"\" ws \":\" ws json-object ws \"}}\"\n",
            "tool-name  ::= {tool_names}\n",
            "json-object ::= \"{{\" ws (json-kv (\",\" ws json-kv)*)? ws \"}}\"\n",
            "json-kv    ::= json-string ws \":\" ws json-value\n",
            "json-value  ::= json-string | json-number | json-object | json-array | \"true\" | \"false\" | \"null\"\n",
            "json-string ::= \"\\\"\" ([^\"\\\\] | \"\\\\\" [\"\\\\/bfnrt] | \"\\\\u\" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])* \"\\\"\"\n",
            "json-number ::= \"-\"? ([0-9] | [1-9] [0-9]*) (\".\" [0-9]+)? ([eE] [+-]? [0-9]+)?\n",
            "json-array  ::= \"[\" ws (json-value (\",\" ws json-value)*)? ws \"]\"\n",
            "ws         ::= [ \\t\\n\\r]*\n",
        ),
        tool_names = tool_names,
    )
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_registry_has_20_tools() {
        let registry = ToolRegistry::default_v1();
        assert_eq!(registry.tools().len(), 20);
    }

    #[test]
    fn grammar_contains_all_tool_names() {
        let registry = ToolRegistry::default_v1();
        let grammar = registry.grammar();
        for tool in registry.tools() {
            assert!(
                grammar.contains(tool.name),
                "grammar missing tool `{}`",
                tool.name
            );
        }
    }

    #[test]
    fn parse_call_valid() {
        let registry = ToolRegistry::default_v1();
        let raw = r#"{"tool": "type_text", "arguments": {"text": "hello world"}}"#;
        let call = registry.parse_call(raw).unwrap();
        assert_eq!(call.tool, "type_text");
        assert_eq!(call.arguments["text"], "hello world");
    }

    #[test]
    fn parse_call_no_arguments_field_defaults_to_empty() {
        let registry = ToolRegistry::default_v1();
        let raw = r#"{"tool": "media_play_pause"}"#;
        let call = registry.parse_call(raw).unwrap();
        assert_eq!(call.tool, "media_play_pause");
        assert!(call.arguments.is_object());
    }

    #[test]
    fn parse_call_unknown_tool_errors() {
        let registry = ToolRegistry::default_v1();
        let raw = r#"{"tool": "explode", "arguments": {}}"#;
        assert!(registry.parse_call(raw).is_err());
    }

    #[test]
    fn parse_call_malformed_json_errors() {
        let registry = ToolRegistry::default_v1();
        assert!(registry.parse_call("not-json").is_err());
    }

    #[test]
    fn all_tool_names_are_unique() {
        let tools = default_tools();
        let mut names: Vec<_> = tools.iter().map(|t| t.name).collect();
        let count = names.len();
        names.sort_unstable();
        names.dedup();
        assert_eq!(names.len(), count, "duplicate tool names detected");
    }

    #[test]
    fn grammar_starts_with_root_rule() {
        let grammar = build_gbnf_grammar(&default_tools());
        assert!(
            grammar.starts_with("root"),
            "GBNF grammar must start with the root rule"
        );
    }
}
