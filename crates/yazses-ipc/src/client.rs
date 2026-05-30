use anyhow::Context;
use serde_json::Value;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::UnixStream;

use crate::protocol::{Request, Response, JSONRPC_VERSION};

/// Async JSON-RPC client over a Unix-domain socket.
///
/// One call per connection — matches the v0.4 wire contract (adr-010).
pub struct IpcClient {
    socket_path: std::path::PathBuf,
    next_id: std::sync::atomic::AtomicU64,
}

impl IpcClient {
    pub fn new(socket_path: impl Into<std::path::PathBuf>) -> Self {
        Self {
            socket_path: socket_path.into(),
            next_id: std::sync::atomic::AtomicU64::new(1),
        }
    }

    pub async fn call(
        &self,
        method: &str,
        params: serde_json::Map<String, Value>,
    ) -> anyhow::Result<Value> {
        let id = self
            .next_id
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);

        let req = Request {
            jsonrpc: JSONRPC_VERSION.into(),
            method: method.into(),
            params,
            id: Some(Value::Number(id.into())),
        };

        let stream = UnixStream::connect(&self.socket_path)
            .await
            .with_context(|| {
                format!(
                    "cannot connect to daemon socket at {}",
                    self.socket_path.display()
                )
            })?;

        let (reader, mut writer) = stream.into_split();

        let mut line = serde_json::to_string(&req)?;
        line.push('\n');
        writer.write_all(line.as_bytes()).await?;

        let mut resp_line = String::new();
        BufReader::new(reader).read_line(&mut resp_line).await?;

        let resp: Response = serde_json::from_str(&resp_line)?;
        if let Some(err) = resp.error {
            anyhow::bail!("RPC error {}: {}", err.code, err.message);
        }
        Ok(resp.result.unwrap_or(Value::Null))
    }
}

/// Blocking thin wrapper over `IpcClient` for use in the synchronous CLI.
pub struct SyncIpcClient {
    inner: IpcClient,
    rt: tokio::runtime::Runtime,
}

impl SyncIpcClient {
    pub fn new(socket_path: impl Into<std::path::PathBuf>) -> anyhow::Result<Self> {
        Ok(Self {
            inner: IpcClient::new(socket_path),
            rt: tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()?,
        })
    }

    pub fn call(
        &self,
        method: &str,
        params: serde_json::Map<String, Value>,
    ) -> anyhow::Result<Value> {
        self.rt.block_on(self.inner.call(method, params))
    }
}
