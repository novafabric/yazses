use std::path::PathBuf;

use crate::protocol::{EditorBridge, EditorContext};

/// Neovim LSP context bridge — connects to the `$NVIM` Unix socket (adr-006).
///
/// On each `get_context()` call the bridge opens a fresh connection, runs
/// the Lua queries, and returns the snapshot.  Connection is intentionally
/// per-call: the daemon may outlive multiple nvim sessions.
///
/// **Feature gate:** `--features neovim`
pub struct NeovimBridge {
    #[allow(dead_code)]
    socket_path: Option<String>,
}

impl NeovimBridge {
    pub fn new(socket_path: Option<String>) -> anyhow::Result<Self> {
        #[cfg(feature = "neovim")]
        {
            Ok(Self { socket_path })
        }
        #[cfg(not(feature = "neovim"))]
        {
            let _ = socket_path;
            anyhow::bail!(
                "NeovimBridge requires the `neovim` feature; \
                 rebuild with `--features neovim`."
            )
        }
    }
}

#[async_trait::async_trait]
impl EditorBridge for NeovimBridge {
    fn name(&self) -> &str {
        "neovim"
    }

    async fn get_context(&self) -> anyhow::Result<Option<EditorContext>> {
        #[cfg(feature = "neovim")]
        {
            let path = self
                .socket_path
                .clone()
                .or_else(|| std::env::var("NVIM").ok())
                .ok_or_else(|| anyhow::anyhow!("$NVIM not set and no socket_path configured"))?;
            get_neovim_context(&path).await.map(Some)
        }
        #[cfg(not(feature = "neovim"))]
        {
            anyhow::bail!("NeovimBridge not compiled in (missing `neovim` feature)")
        }
    }

    async fn get_active_file(&self) -> anyhow::Result<Option<PathBuf>> {
        Ok(self.get_context().await?.and_then(|c| c.file_path))
    }
}

// ── nvim-rs implementation ────────────────────────────────────────────────────

#[cfg(feature = "neovim")]
async fn get_neovim_context(socket: &str) -> anyhow::Result<EditorContext> {
    use crate::protocol::{CursorContext, Symbol};
    use nvim_rs::{create::tokio as nvim_tokio, Handler};

    #[derive(Clone, Default)]
    struct NopHandler;

    #[async_trait::async_trait]
    impl Handler for NopHandler {
        type Writer = nvim_rs::compat::tokio::Compat<tokio::io::WriteHalf<tokio::net::UnixStream>>;
    }

    let (nvim, io) = nvim_tokio::new_unix_socket(socket, NopHandler)
        .await
        .map_err(|e| anyhow::anyhow!("nvim connect: {e}"))?;
    let _io = tokio::spawn(io);

    // Current buffer name → file path.
    let buf = nvim.get_current_buf().await?;
    let name: String = buf.get_name(&nvim).await?;
    let file_path = if name.is_empty() {
        None
    } else {
        Some(PathBuf::from(&name))
    };

    // Detect language from filetype.
    let ft: String = nvim
        .exec_lua("return vim.bo.filetype", vec![])
        .await
        .unwrap_or_default()
        .to_string();
    let language = if ft.is_empty() { None } else { Some(ft) };

    // Cursor position.
    let win = nvim.get_current_win().await?;
    let cursor = win.get_cursor(&nvim).await.ok();
    let cursor_ctx = cursor.map(|(row, col)| CursorContext {
        line: row as u32,
        col: col as u32,
        surrounding_text: String::new(),
    });

    // LSP symbols via Lua (best-effort; returns empty list on error).
    let symbols = collect_lsp_symbols(&nvim).await.unwrap_or_default();

    Ok(EditorContext {
        file_path,
        language,
        project_root: None,
        recent_symbols: symbols,
        imports: vec![],
        cursor: cursor_ctx,
        recent_edits: vec![],
    })
}

#[cfg(feature = "neovim")]
async fn collect_lsp_symbols(
    nvim: &nvim_rs::Neovim<
        nvim_rs::compat::tokio::Compat<tokio::io::WriteHalf<tokio::net::UnixStream>>,
    >,
) -> anyhow::Result<Vec<Symbol>> {
    use rmpv::Value;

    // Request document symbols from the first available LSP client.
    let lua = r#"
        local clients = vim.lsp.get_clients({bufnr=0})
        if #clients == 0 then return nil end
        local params = vim.lsp.util.make_text_document_params(0)
        local result = clients[1].request_sync(
            'textDocument/documentSymbol', {textDocument=params}, 1000, 0)
        if not result or not result.result then return nil end
        local out = {}
        for _, s in ipairs(result.result) do
            table.insert(out, {name=s.name, kind=tostring(s.kind)})
        end
        return out
    "#;

    let val = nvim.exec_lua(lua, vec![]).await?;

    let mut symbols = Vec::new();
    if let Value::Array(arr) = val {
        for item in arr.into_iter().take(32) {
            if let Value::Map(fields) = item {
                let mut name = String::new();
                let mut kind = String::new();
                for (k, v) in fields {
                    match (k.as_str(), v) {
                        (Some("name"), Value::String(s)) => name = s.into_str().unwrap_or_default(),
                        (Some("kind"), Value::String(s)) => kind = s.into_str().unwrap_or_default(),
                        _ => {}
                    }
                }
                if !name.is_empty() {
                    symbols.push(Symbol {
                        name,
                        kind,
                        file: None,
                    });
                }
            }
        }
    }
    Ok(symbols)
}
