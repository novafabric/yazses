use std::path::PathBuf;
use std::sync::Arc;

use crate::protocol::{EditorBridge, EditorContext};

/// VS Code LSP context bridge — listens on a local TCP port for context pushes
/// from the YazSes VS Code companion extension (adr-006).
///
/// Protocol: newline-delimited JSON on `127.0.0.1:<port>`.  The extension
/// connects, sends one `EditorContext` JSON object per change, and holds the
/// socket open.  The bridge stores the most-recent snapshot.
///
/// Default port: 57843.  Configurable via `VSCodeBridge::new(port)`.
///
/// **Feature gate:** `--features vscode`
pub struct VSCodeBridge {
    #[allow(dead_code)]
    port: u16,
    #[allow(dead_code)]
    context: Arc<tokio::sync::RwLock<Option<EditorContext>>>,
}

impl VSCodeBridge {
    pub fn new(port: u16) -> anyhow::Result<Self> {
        #[cfg(feature = "vscode")]
        {
            Ok(Self {
                port,
                context: Arc::new(tokio::sync::RwLock::new(None)),
            })
        }
        #[cfg(not(feature = "vscode"))]
        {
            let _ = port;
            anyhow::bail!(
                "VSCodeBridge requires the `vscode` feature; \
                 rebuild with `--features vscode`."
            )
        }
    }

    /// Spawns the background TCP listener task.  Call once at daemon startup.
    pub async fn start(&self) -> anyhow::Result<()> {
        #[cfg(feature = "vscode")]
        {
            let listener =
                tokio::net::TcpListener::bind(format!("127.0.0.1:{}", self.port)).await?;
            let ctx = Arc::clone(&self.context);
            tokio::spawn(accept_loop(listener, ctx));
            tracing::info!(port = self.port, "VSCodeBridge listening");
            Ok(())
        }
        #[cfg(not(feature = "vscode"))]
        {
            anyhow::bail!("VSCodeBridge not compiled in (missing `vscode` feature)")
        }
    }
}

#[async_trait::async_trait]
impl EditorBridge for VSCodeBridge {
    fn name(&self) -> &str {
        "vscode"
    }

    async fn get_context(&self) -> anyhow::Result<Option<EditorContext>> {
        #[cfg(feature = "vscode")]
        {
            Ok(self.context.read().await.clone())
        }
        #[cfg(not(feature = "vscode"))]
        {
            anyhow::bail!("VSCodeBridge not compiled in (missing `vscode` feature)")
        }
    }

    async fn get_active_file(&self) -> anyhow::Result<Option<PathBuf>> {
        Ok(self.get_context().await?.and_then(|c| c.file_path))
    }
}

// ── TCP accept loop (compiled only with `vscode` feature) ────────────────────

#[cfg(feature = "vscode")]
async fn accept_loop(
    listener: tokio::net::TcpListener,
    ctx: Arc<tokio::sync::RwLock<Option<EditorContext>>>,
) {
    loop {
        match listener.accept().await {
            Ok((stream, addr)) => {
                tracing::debug!(%addr, "VSCode extension connected");
                let ctx2 = Arc::clone(&ctx);
                tokio::spawn(handle_connection(stream, ctx2));
            }
            Err(e) => {
                tracing::warn!("VSCodeBridge accept error: {e}");
                break;
            }
        }
    }
}

#[cfg(feature = "vscode")]
async fn handle_connection(
    stream: tokio::net::TcpStream,
    ctx: Arc<tokio::sync::RwLock<Option<EditorContext>>>,
) {
    use tokio::io::{AsyncBufReadExt, BufReader};

    let reader = BufReader::new(stream);
    let mut lines = reader.lines();
    while let Ok(Some(line)) = lines.next_line().await {
        match serde_json::from_str::<EditorContext>(&line) {
            Ok(new_ctx) => {
                *ctx.write().await = Some(new_ctx);
            }
            Err(e) => {
                tracing::warn!("VSCodeBridge parse error: {e}");
            }
        }
    }
}
