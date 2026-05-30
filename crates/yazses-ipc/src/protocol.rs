// JSON-RPC 2.0 framing — mirrors v0.4 yazses/ipc/protocol.py exactly.
// One connection per request; newline-delimited JSON; no batching.

use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const JSONRPC_VERSION: &str = "2.0";

// JSON-RPC error codes
pub const PARSE_ERROR: i32 = -32700;
pub const INVALID_REQUEST: i32 = -32600;
pub const METHOD_NOT_FOUND: i32 = -32601;
pub const INVALID_PARAMS: i32 = -32602;
pub const INTERNAL_ERROR: i32 = -32603;
pub const HANDLER_FAILED: i32 = -32000;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Request {
    pub jsonrpc: String,
    pub method: String,
    #[serde(default)]
    pub params: serde_json::Map<String, Value>,
    pub id: Option<Value>,
}

impl Request {
    pub fn parse(line: &str) -> anyhow::Result<Self> {
        let req: Self = serde_json::from_str(line)?;
        anyhow::ensure!(
            req.jsonrpc == JSONRPC_VERSION,
            "unsupported jsonrpc version: {}",
            req.jsonrpc
        );
        Ok(req)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RpcError {
    pub code: i32,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<Value>,
}

impl RpcError {
    pub fn new(code: i32, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
            data: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Response {
    pub jsonrpc: String,
    pub id: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<RpcError>,
}

impl Response {
    pub fn ok(id: Option<Value>, result: impl Serialize) -> anyhow::Result<Self> {
        Ok(Self {
            jsonrpc: JSONRPC_VERSION.into(),
            id,
            result: Some(serde_json::to_value(result)?),
            error: None,
        })
    }

    pub fn err(id: Option<Value>, error: RpcError) -> Self {
        Self {
            jsonrpc: JSONRPC_VERSION.into(),
            id,
            result: None,
            error: Some(error),
        }
    }

    pub fn to_line(&self) -> anyhow::Result<String> {
        Ok(serde_json::to_string(self)?)
    }
}
