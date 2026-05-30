use std::collections::HashMap;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::sync::Arc;

use anyhow::Context;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::UnixListener;
use tokio::sync::RwLock;
use tracing::{debug, error, warn};

use crate::protocol::{
    Request, Response, RpcError, HANDLER_FAILED, INTERNAL_ERROR, METHOD_NOT_FOUND, PARSE_ERROR,
};
use crate::Handler;

/// Async JSON-RPC server over a Unix-domain socket.
///
/// Wire contract (adr-010): one connection per call; the client writes one
/// newline-terminated JSON request, reads one newline-terminated JSON response,
/// and disconnects. The socket is mode 0600 (owner-only) per NFR-SEC04.
pub struct IpcServer {
    socket_path: PathBuf,
    handlers: Arc<RwLock<HashMap<String, Handler>>>,
}

impl IpcServer {
    pub fn new(socket_path: impl Into<PathBuf>) -> Self {
        Self {
            socket_path: socket_path.into(),
            handlers: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    pub async fn register(&self, method: impl Into<String>, handler: Handler) {
        self.handlers.write().await.insert(method.into(), handler);
    }

    /// Bind the socket and spawn the accept loop. Returns immediately.
    pub async fn serve(self: Arc<Self>) -> anyhow::Result<()> {
        let path = &self.socket_path;
        if let Some(parent) = path.parent() {
            tokio::fs::create_dir_all(parent).await?;
        }
        if path.exists() {
            tokio::fs::remove_file(path).await.ok();
        }

        let listener = UnixListener::bind(path)
            .with_context(|| format!("binding IPC socket at {}", path.display()))?;

        // mode 0600 — owner read/write only (NFR-SEC04)
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;

        tracing::info!("IPC server listening on {}", path.display());

        let server = self.clone();
        tokio::spawn(async move {
            loop {
                match listener.accept().await {
                    Ok((stream, _)) => {
                        let s = server.clone();
                        tokio::spawn(async move {
                            if let Err(e) = s.handle_connection(stream).await {
                                debug!("IPC connection error: {e}");
                            }
                        });
                    }
                    Err(e) => {
                        warn!("IPC accept error: {e}");
                    }
                }
            }
        });

        Ok(())
    }

    async fn handle_connection(&self, stream: tokio::net::UnixStream) -> anyhow::Result<()> {
        let (reader, mut writer) = stream.into_split();
        let mut lines = BufReader::new(reader).lines();

        let line = match lines.next_line().await? {
            Some(l) => l,
            None => return Ok(()),
        };

        let response = match Request::parse(&line) {
            Err(e) => Response::err(None, RpcError::new(PARSE_ERROR, e.to_string())),
            Ok(req) => {
                let id = req.id.clone();
                let handlers = self.handlers.read().await;
                match handlers.get(&req.method) {
                    None => Response::err(
                        id,
                        RpcError::new(
                            METHOD_NOT_FOUND,
                            format!("unknown method: {:?}", req.method),
                        ),
                    ),
                    Some(handler) => {
                        let h = handler.clone();
                        drop(handlers);
                        match h(req).await {
                            Ok(result) => match Response::ok(id.clone(), result) {
                                Ok(r) => r,
                                Err(e) => {
                                    error!("serialising result: {e}");
                                    Response::err(id, RpcError::new(INTERNAL_ERROR, e.to_string()))
                                }
                            },
                            Err(e) => {
                                Response::err(id, RpcError::new(HANDLER_FAILED, e.to_string()))
                            }
                        }
                    }
                }
            }
        };

        let mut line = response.to_line()?;
        line.push('\n');
        writer.write_all(line.as_bytes()).await?;
        Ok(())
    }
}
