pub mod client;
pub mod protocol;
pub mod server;

pub use client::{IpcClient, SyncIpcClient};
pub use protocol::{Request, Response, RpcError};
pub use server::IpcServer;

/// Async handler signature: takes a `Request`, returns a JSON `Value`.
// adr-010: all v0.4-compatible handlers share this signature.
pub type Handler = std::sync::Arc<
    dyn Fn(
            Request,
        ) -> std::pin::Pin<
            Box<dyn std::future::Future<Output = anyhow::Result<serde_json::Value>> + Send>,
        > + Send
        + Sync,
>;

/// Construct a `Handler` from an async closure or async block.
///
/// ```ignore
/// server.register("ping", handler!(|_req| async { Ok(serde_json::json!("pong")) })).await;
/// ```
#[macro_export]
macro_rules! handler {
    ($f:expr) => {{
        let f = $f;
        std::sync::Arc::new(
            move |req: $crate::Request| -> std::pin::Pin<
                Box<dyn std::future::Future<Output = anyhow::Result<serde_json::Value>> + Send>,
            > { Box::pin(f(req)) },
        ) as $crate::Handler
    }};
}
