use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Symbol {
    pub name: String,
    pub kind: String,
    pub file: Option<PathBuf>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Import {
    pub module: String,
    pub items: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CursorContext {
    pub line: u32,
    pub col: u32,
    pub surrounding_text: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Edit {
    pub text: String,
    pub timestamp_ms: u64,
}

/// Full editor state snapshot provided to the ASR + LLM pipeline (adr-006).
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct EditorContext {
    pub file_path: Option<PathBuf>,
    /// Language identifier: "rust", "python", "tsx", etc.
    pub language: Option<String>,
    pub project_root: Option<PathBuf>,
    /// Up to 32 most-recently-used LSP symbols.
    pub recent_symbols: Vec<Symbol>,
    pub imports: Vec<Import>,
    pub cursor: Option<CursorContext>,
    pub recent_edits: Vec<Edit>,
}

impl EditorContext {
    /// Builds the Whisper `initial_prompt` string: comma-separated symbol names,
    /// budget-capped at `max_bpe` tokens (≈ 4 chars each).  Per adr-006: ≤ 224 BPE.
    pub fn to_initial_prompt(&self, max_bpe: usize) -> String {
        let budget = max_bpe * 4;
        let mut out = String::new();
        for sym in &self.recent_symbols {
            let seg = if out.is_empty() {
                sym.name.clone()
            } else {
                format!(", {}", sym.name)
            };
            if out.len() + seg.len() > budget {
                break;
            }
            out.push_str(&seg);
        }
        out
    }

    /// Renders a structured `<editor_context>` block for the LLM system prompt.
    pub fn to_llm_block(&self) -> String {
        let mut buf = String::from("<editor_context>\n");
        if let Some(p) = &self.file_path {
            buf.push_str(&format!("file: {}\n", p.display()));
        }
        if let Some(lang) = &self.language {
            buf.push_str(&format!("language: {lang}\n"));
        }
        if let Some(root) = &self.project_root {
            buf.push_str(&format!("project: {}\n", root.display()));
        }
        if !self.recent_symbols.is_empty() {
            let names: Vec<_> = self
                .recent_symbols
                .iter()
                .map(|s| s.name.as_str())
                .collect();
            buf.push_str(&format!("symbols: {}\n", names.join(", ")));
        }
        if let Some(cursor) = &self.cursor {
            buf.push_str(&format!("cursor: {}:{}\n", cursor.line, cursor.col));
            if !cursor.surrounding_text.is_empty() {
                buf.push_str(&format!("context: {}\n", cursor.surrounding_text));
            }
        }
        buf.push_str("</editor_context>");
        buf
    }
}

/// Minimal info about the currently focused OS window.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WindowInfo {
    /// WM_CLASS / app_id / process name (lowercase).
    pub app_id: String,
    pub title: String,
    pub pid: Option<u32>,
}

impl WindowInfo {
    /// True when `app_id` matches a known editor process name.
    pub fn is_editor(&self) -> bool {
        matches!(
            self.app_id.to_lowercase().as_str(),
            "nvim"
                | "neovim"
                | "code"
                | "code-oss"
                | "vscodium"
                | "helix"
                | "hx"
                | "emacs"
                | "vim"
                | "gvim"
                | "jetbrains-idea"
                | "clion"
                | "pycharm"
                | "webstorm"
                | "rider"
        )
    }
}

/// Detects the currently focused OS window (adr-006 §WindowDetector).
#[async_trait::async_trait]
pub trait WindowDetector: Send + Sync {
    fn name(&self) -> &str;
    async fn focused_window(&self) -> anyhow::Result<Option<WindowInfo>>;
}

/// Queries the active editor for LSP context (adr-006 §EditorBridge).
#[async_trait::async_trait]
pub trait EditorBridge: Send + Sync {
    fn name(&self) -> &str;
    async fn get_context(&self) -> anyhow::Result<Option<EditorContext>>;
    async fn get_active_file(&self) -> anyhow::Result<Option<PathBuf>>;
}
