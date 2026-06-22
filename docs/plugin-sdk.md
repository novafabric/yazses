# YazSes Plugin SDK

> ⚠️ **This document describes the paused/archived Rust exploration**
> (`archive/rust-hci-v1` branch), **not the shipping product.** The product you
> install (Python, `main`) has no Rust-style plugin SDK — extend it instead with
> voice **macros**, a personal **vocabulary** (`yazses vocab`), and config
> (`yazses features` / `yazses hotkey`). See the README's "Two versions of
> YazSes" section for what ships vs. what's archived.

**Codebase version:** v1.0.0-dev.5  
**Rust edition:** 2021, MSRV 1.85

This document covers every extension point in the YazSes Rust workspace. For each one you will find the trait definition (taken verbatim from source), an explanation of every method, a minimal working stub, and the wiring step that makes the daemon pick it up.

---

## Table of contents

1. [Workspace layout](#workspace-layout)
2. [Building and testing](#building-and-testing)
3. [Extension point 1 — Input backend](#extension-point-1--input-backend)
4. [Extension point 2 — STT backend](#extension-point-2--stt-backend)
5. [Extension point 3 — LLM backend](#extension-point-3--llm-backend)
6. [Extension point 4 — Editor bridge](#extension-point-4--editor-bridge)
7. [Extension point 5 — Dispatcher tool](#extension-point-5--dispatcher-tool)
8. [Cargo feature flags reference](#cargo-feature-flags-reference)

---

## Workspace layout

```
yazses/
├── Cargo.toml                   workspace manifest
└── crates/
    ├── yazses-inputs/           InputBackend trait + evdev + EMG
    ├── yazses-audio/            cpal capture, RMS/Silero VAD
    ├── yazses-stt/              STTBackend trait + STTRouter + Moonshine + Whisper
    ├── yazses-llm/              LLMBackend trait + ToolRegistry + llama.cpp + Ollama
    ├── yazses-editors/          EditorBridge / WindowDetector traits + bridges
    ├── yazses-core/             Daemon, Dispatcher, state machine
    ├── yazses-ipc/              JSON-RPC 2.0 IPC
    ├── yazses-memory/           PersonalMemory, OnnxEmbedder, SQLCipher
    ├── yazses-atspi/            Linux AT-SPI screen-reader announcer
    ├── yazses-nvda/             Windows NVDA controller
    └── yazses-cli/              `yazses` binary (clap)
```

Each trait lives in a `protocol.rs` module inside its crate; the corresponding `lib.rs` re-exports it. All trait objects must be `Send + Sync`.

---

## Building and testing

```bash
# Build the workspace (no optional backends)
cargo build --workspace

# Enable specific optional backends
cargo build --workspace --features yazses-stt/whisper,yazses-llm/llama-cpp

# Run the full test suite
cargo test --workspace

# Run tests for a single crate
cargo test -p yazses-stt
cargo test -p yazses-inputs

# Release build (size-optimised; LTO fat; symbols stripped)
cargo build --workspace --release
```

Feature flags are per-crate. To pass them on the command line, prefix with the crate name: `--features yazses-llm/ollama`. When building the daemon binary (`yazses-core`) you pull in all the backends you need from the crates it depends on.

---

## Extension point 1 — Input backend

**Crate:** `crates/yazses-inputs`  
**Trait source:** `crates/yazses-inputs/src/protocol.rs`

### Trait definition

```rust
/// Uniform interface for all input modalities (adr-005).
///
/// Implementations must be `Send + Sync` so they can be held behind an Arc.
/// `start()` is non-blocking: it spawns a task and returns immediately.
/// Events are delivered over the supplied `mpsc::Sender`.
#[async_trait::async_trait]
pub trait InputBackend: Send + Sync {
    fn name(&self) -> &str;
    fn capabilities(&self) -> &[&'static str];
    async fn start(&mut self, tx: tokio::sync::mpsc::Sender<InputEvent>) -> anyhow::Result<()>;
    fn calibrate(&self, corpus: &[CalibrationSample]) -> Option<CalibrationArtifact>;
}
```

### Supporting types

```rust
pub enum InputEvent {
    HoldStart { ts: f64, leaked: u32 },
    PartialText { ts: f64, text: String },
    Gesture { ts: f64, kind: String, params: serde_json::Value },
    HoldEnd { ts: f64 },
    CalibrationReady { artifact: CalibrationArtifact },
}

pub struct CalibrationArtifact {
    pub backend: String,
    pub payload: serde_json::Value,
}

pub struct CalibrationSample {
    pub label: String,
    pub data:  serde_json::Value,
}

// Stable capability label constants
pub const CAP_HOLD:         &str = "hold";
pub const CAP_GESTURE:      &str = "gesture";
pub const CAP_PARTIAL_TEXT: &str = "partial_text";
pub const CAP_CALIBRATION:  &str = "calibration";
```

### Method contract

| Method | Contract |
|---|---|
| `name()` | Short human-readable label used in logs and `yazses status`. |
| `capabilities()` | Return a slice of the `CAP_*` constants this backend actually emits. The daemon uses this to decide whether to advertise calibration in `yazses enroll`. |
| `start(tx)` | Spawn a background task (typically `tokio::spawn`) that sends `InputEvent`s to `tx`. Return immediately. Return `Err` only if the device cannot be opened at all. |
| `calibrate(corpus)` | Optional. Given a set of labelled samples, compute a `CalibrationArtifact` and return it. Return `None` if the backend does not support calibration. The artifact is serialised to config and handed back on the next start. |

### Minimal stub

```rust
// crates/yazses-inputs/src/my_backend.rs

use crate::protocol::{
    CalibrationArtifact, CalibrationSample, InputBackend, InputEvent, CAP_HOLD,
};

pub struct MyInputBackend {
    // device handle, config, etc.
}

#[async_trait::async_trait]
impl InputBackend for MyInputBackend {
    fn name(&self) -> &str {
        "my-input"
    }

    fn capabilities(&self) -> &[&'static str] {
        &[CAP_HOLD]
    }

    async fn start(
        &mut self,
        tx: tokio::sync::mpsc::Sender<InputEvent>,
    ) -> anyhow::Result<()> {
        let tx = tx.clone();
        tokio::spawn(async move {
            loop {
                // Poll your device here …
                let now = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_secs_f64();

                // Example: fire HoldStart / HoldEnd on physical button
                tx.send(InputEvent::HoldStart { ts: now, leaked: 0 })
                    .await
                    .ok();
                // … wait for release …
                tx.send(InputEvent::HoldEnd { ts: now }).await.ok();
            }
        });
        Ok(())
    }

    fn calibrate(&self, _corpus: &[CalibrationSample]) -> Option<CalibrationArtifact> {
        None
    }
}
```

### Feature flag (optional)

If your backend requires an optional system dependency, declare it as a feature in `crates/yazses-inputs/Cargo.toml`:

```toml
[dependencies.my-device-crate]
version = "1"
optional = true

[features]
my-backend = ["dep:my-device-crate"]
```

Gate the module in `lib.rs`:

```rust
#[cfg(feature = "my-backend")]
pub mod my_backend;
#[cfg(feature = "my-backend")]
pub use my_backend::MyInputBackend;
```

### Wiring into the daemon

The daemon (`crates/yazses-core/src/daemon.rs`) constructs the input backend directly. Add a branch to the backend-selection block (search for `KeyboardHoldBackend` for the existing pattern):

```rust
// In daemon.rs — backend selection
#[cfg(feature = "yazses-inputs/my-backend")]
let input: Box<dyn InputBackend> = Box::new(MyInputBackend::new(&config)?);

// Pass `input` to the pipeline the same way KeyboardHoldBackend is passed today.
```

---

## Extension point 2 — STT backend

**Crate:** `crates/yazses-stt`  
**Trait source:** `crates/yazses-stt/src/protocol.rs`

### Trait definition

```rust
/// Uniform interface for all STT backends (adr-002).
#[async_trait::async_trait]
pub trait STTBackend: Send + Sync {
    /// Short human-readable name used in logs and status responses.
    fn name(&self) -> &str;

    /// Soft upper bound (seconds) this backend handles well.
    ///
    /// `STTRouter` uses this to select between backends. A value of
    /// `f32::MAX` signals "no upper bound" (long-form path).
    fn preferred_max_s(&self) -> f32;

    /// Transcribe a complete audio buffer.
    ///
    /// `audio`: mono f32 PCM.
    /// `sample_rate`: samples per second (16 000 for Moonshine; any for Whisper).
    async fn transcribe(
        &self,
        audio: &[f32],
        sample_rate: u32,
        options: TranscribeOptions,
    ) -> anyhow::Result<Transcript>;
}
```

### Supporting types

```rust
pub struct Transcript {
    pub text:       String,
    /// BCP-47 tag, e.g. "en" or "fa".
    pub language:   Option<String>,
    /// Wall-clock inference time in milliseconds.
    pub latency_ms: u64,
    /// Model-reported confidence in [0, 1]; 1.0 if the backend does not expose one.
    pub confidence: f32,
}

#[derive(Default)]
pub struct TranscribeOptions {
    /// Whisper `initial_prompt` injected from LSP context. Streaming backends ignore this.
    pub initial_prompt: Option<String>,
    /// Force a specific language; None → auto-detect.
    pub language: Option<String>,
}
```

### Method contract

| Method | Contract |
|---|---|
| `name()` | Short label for logs. |
| `preferred_max_s()` | The `STTRouter` uses this threshold: audio whose duration is at or below this value is routed to the backend with the lower threshold (the "streaming" slot). Return `f32::MAX` for a backend that accepts any length. |
| `transcribe(audio, sample_rate, options)` | Perform synchronous (blocking-within-async) or truly async inference. Return a `Transcript` or an error. The daemon calls this from within a Tokio task, so blocking is acceptable only if you use `tokio::task::spawn_blocking`. |

### How STTRouter selects backends

`STTRouter` is constructed with two backends:

```rust
let router = STTRouter::with_default_threshold(
    Arc::new(streaming_backend),   // ≤ 4 s audio
    Arc::new(longform_backend),    // > 4 s audio
);
```

`DEFAULT_THRESHOLD_S` is `4.0`. To add a third backend, replace one of the two slots or compose your own router on top of `STTBackend`.

### Minimal stub

```rust
// crates/yazses-stt/src/my_stt_backend.rs

use crate::protocol::{STTBackend, TranscribeOptions, Transcript};

pub struct MySttBackend {
    // model handle, config, etc.
}

#[async_trait::async_trait]
impl STTBackend for MySttBackend {
    fn name(&self) -> &str {
        "my-stt"
    }

    fn preferred_max_s(&self) -> f32 {
        4.0 // prefer the streaming slot
    }

    async fn transcribe(
        &self,
        audio: &[f32],
        sample_rate: u32,
        options: TranscribeOptions,
    ) -> anyhow::Result<Transcript> {
        let start = std::time::Instant::now();

        // Run inference (example: call into a C library via FFI)
        let text = my_infer(audio, sample_rate, options.initial_prompt.as_deref())?;

        Ok(Transcript {
            text,
            language: None,
            latency_ms: start.elapsed().as_millis() as u64,
            confidence: 1.0,
        })
    }
}
```

### Feature flag

```toml
# crates/yazses-stt/Cargo.toml
[dependencies.my-infer-crate]
version = "1"
optional = true

[features]
my-stt = ["dep:my-infer-crate"]
```

Gate in `lib.rs`:

```rust
#[cfg(feature = "my-stt")]
pub mod my_stt_backend;
#[cfg(feature = "my-stt")]
pub use my_stt_backend::MySttBackend;
```

### Wiring into STTRouter

In `crates/yazses-core/src/daemon.rs`, find the block that constructs `STTRouter` (search for `STTRouter::with_default_threshold`) and substitute your backend:

```rust
#[cfg(feature = "yazses-stt/my-stt")]
let streaming: Arc<dyn STTBackend> = Arc::new(MySttBackend::new(&config.stt)?);
#[cfg(not(feature = "yazses-stt/my-stt"))]
let streaming: Arc<dyn STTBackend> = Arc::new(MoonshineV2Backend::new(&config.stt)?);

let stt_router = STTRouter::with_default_threshold(streaming, longform);
```

---

## Extension point 3 — LLM backend

**Crate:** `crates/yazses-llm`  
**Trait source:** `crates/yazses-llm/src/protocol.rs`

### Trait definition

```rust
/// Uniform interface for all LLM backends (adr-003).
#[async_trait::async_trait]
pub trait LLMBackend: Send + Sync {
    fn name(&self) -> &str;
    async fn complete(&self, request: LLMRequest) -> anyhow::Result<LLMOutput>;
}
```

### Supporting types

```rust
pub struct LLMRequest {
    pub system_prompt:  String,
    pub messages:       Vec<Message>,
    /// GBNF grammar for constrained decoding; None for free text.
    pub grammar:        Option<String>,
    /// <editor_context> block from the active EditorBridge (≤ 2 000 BPE tokens).
    pub editor_context: Option<String>,
    pub max_tokens:     u32,
    pub temperature:    f32,
    /// Routing tier. v1.0 only supports Tier::Fast; Tier::Deep returns an error.
    pub tier:           Tier,
}

pub enum LLMOutput {
    Text(String),
    ToolCall(ToolCall),
}

pub struct ToolCall {
    pub tool:      String,
    pub arguments: serde_json::Value,
}

pub enum Tier { Fast, Deep }
```

Use `LLMRequest::builder(system_prompt)` for a fluent construction API.

### Method contract

| Method | Contract |
|---|---|
| `name()` | Short label. |
| `complete(request)` | Run a single LLM turn. When `request.grammar` is `Some`, the backend must apply grammar-constrained decoding so that every returned `ToolCall` is syntactically valid JSON matching the GBNF. Return `LLMOutput::Text` for free dictation, `LLMOutput::ToolCall` when the model selects a registered tool. The returned `ToolCall.tool` must be one of the names registered in `ToolRegistry`; the daemon validates this. |

### Minimal stub

```rust
// crates/yazses-llm/src/my_llm_backend.rs

use crate::protocol::{LLMBackend, LLMOutput, LLMRequest};

pub struct MyLlmBackend {
    // HTTP client, model ref, etc.
}

#[async_trait::async_trait]
impl LLMBackend for MyLlmBackend {
    fn name(&self) -> &str {
        "my-llm"
    }

    async fn complete(&self, request: LLMRequest) -> anyhow::Result<LLMOutput> {
        // Assemble your prompt from request.system_prompt + request.messages
        // Apply request.grammar if your inference engine supports GBNF
        let raw = my_generate(&request).await?;

        // If the raw output is a JSON tool call, return ToolCall; otherwise Text.
        if raw.trim_start().starts_with('{') {
            // Let ToolRegistry::parse_call() validate it — or parse manually.
            let call: crate::ToolCall = serde_json::from_str(&raw)?;
            Ok(LLMOutput::ToolCall(call))
        } else {
            Ok(LLMOutput::Text(raw))
        }
    }
}
```

### Feature flag

```toml
# crates/yazses-llm/Cargo.toml
[dependencies.my-llm-crate]
version = "1"
optional = true

[features]
my-llm = ["dep:my-llm-crate"]
```

Gate in `lib.rs`:

```rust
#[cfg(feature = "my-llm")]
pub mod my_llm_backend;
#[cfg(feature = "my-llm")]
pub use my_llm_backend::MyLlmBackend;
```

### Wiring into the daemon

In `crates/yazses-core/src/daemon.rs`, find the backend selection for `LLMBackend` and add a branch:

```rust
#[cfg(feature = "yazses-llm/my-llm")]
let llm: Arc<dyn LLMBackend> = Arc::new(MyLlmBackend::new(&config.llm)?);
#[cfg(not(feature = "yazses-llm/my-llm"))]
let llm: Arc<dyn LLMBackend> = Arc::new(OllamaBackend::new(&config.llm));
```

---

## Extension point 4 — Editor bridge

**Crate:** `crates/yazses-editors`  
**Trait sources:** `crates/yazses-editors/src/protocol.rs`

There are two related traits:

### WindowDetector

```rust
/// Detects the currently focused OS window (adr-006 §WindowDetector).
#[async_trait::async_trait]
pub trait WindowDetector: Send + Sync {
    fn name(&self) -> &str;
    async fn focused_window(&self) -> anyhow::Result<Option<WindowInfo>>;
}
```

`WindowInfo`:

```rust
pub struct WindowInfo {
    /// WM_CLASS / app_id / process name (lowercase).
    pub app_id: String,
    pub title:  String,
    pub pid:    Option<u32>,
}
```

`WindowInfo::is_editor()` returns true for known editor `app_id` values (`nvim`, `code`, `helix`, etc.).

### EditorBridge

```rust
/// Queries the active editor for LSP context (adr-006 §EditorBridge).
#[async_trait::async_trait]
pub trait EditorBridge: Send + Sync {
    fn name(&self) -> &str;
    async fn get_context(&self) -> anyhow::Result<Option<EditorContext>>;
    async fn get_active_file(&self) -> anyhow::Result<Option<PathBuf>>;
}
```

`EditorContext`:

```rust
pub struct EditorContext {
    pub file_path:       Option<PathBuf>,
    /// Language identifier: "rust", "python", "tsx", etc.
    pub language:        Option<String>,
    pub project_root:    Option<PathBuf>,
    /// Up to 32 most-recently-used LSP symbols.
    pub recent_symbols:  Vec<Symbol>,
    pub imports:         Vec<Import>,
    pub cursor:          Option<CursorContext>,
    pub recent_edits:    Vec<Edit>,
}
```

`EditorContext` has two helper methods used by the pipeline:

- `to_initial_prompt(max_bpe: usize) -> String` — builds a comma-separated symbol list capped at `max_bpe × 4` characters for Whisper's `initial_prompt`.
- `to_llm_block() -> String` — renders a `<editor_context>…</editor_context>` block for the LLM system prompt.

### Method contracts

| Method | Contract |
|---|---|
| `WindowDetector::focused_window()` | Return the currently focused window, or `None` if nothing is focused or the compositor is unreachable. Never panic. |
| `EditorBridge::get_context()` | Return a snapshot of the active editor state, or `None` if the editor is not running. Should complete within ~100 ms (warm cache budget). |
| `EditorBridge::get_active_file()` | Return the path of the file currently open in the editor, or `None`. |

### Minimal stubs

```rust
// crates/yazses-editors/src/my_detector.rs

use crate::protocol::{WindowDetector, WindowInfo};

pub struct MyWindowDetector;

#[async_trait::async_trait]
impl WindowDetector for MyWindowDetector {
    fn name(&self) -> &str {
        "my-wm"
    }

    async fn focused_window(&self) -> anyhow::Result<Option<WindowInfo>> {
        // Query your compositor via its IPC socket, DBus, etc.
        Ok(Some(WindowInfo {
            app_id: "nvim".into(),
            title:  "main.rs".into(),
            pid:    None,
        }))
    }
}
```

```rust
// crates/yazses-editors/src/my_bridge.rs

use std::path::PathBuf;
use crate::protocol::{EditorBridge, EditorContext};

pub struct MyEditorBridge;

#[async_trait::async_trait]
impl EditorBridge for MyEditorBridge {
    fn name(&self) -> &str {
        "my-editor"
    }

    async fn get_context(&self) -> anyhow::Result<Option<EditorContext>> {
        // Connect to your editor's IPC or extension API.
        Ok(None)
    }

    async fn get_active_file(&self) -> anyhow::Result<Option<PathBuf>> {
        Ok(None)
    }
}
```

### Adding to the WindowDetector tier list

Window detectors are tried in priority order by `probe_window_detector()` in `crates/yazses-editors/src/probe.rs`. Add a new tier before `NullWindowDetector`:

```rust
// crates/yazses-editors/src/probe.rs

// ... existing tiers 1–4 ...

// Tier 5 — My compositor
#[cfg(all(target_os = "linux", feature = "my-wm"))]
if let Some(d) = crate::my_detector::MyWindowDetector::try_connect().await {
    tracing::info!("WindowDetector: using my-wm (tier 5)");
    return Box::new(d);
}

// Tier 6 — Null fallback (always last)
Box::new(NullWindowDetector)
```

### Feature flag

```toml
# crates/yazses-editors/Cargo.toml
[dependencies.my-compositor-crate]
version = "1"
optional = true

[features]
my-wm = ["dep:my-compositor-crate"]
```

Gate in `lib.rs`:

```rust
#[cfg(all(target_os = "linux", feature = "my-wm"))]
pub mod my_detector;
#[cfg(all(target_os = "linux", feature = "my-wm"))]
pub use my_detector::MyWindowDetector;
```

### Wiring the EditorBridge

In `crates/yazses-core/src/daemon.rs`, the `EditorBridge` is selected based on which editor the `WindowDetector` reports. Add a branch to the editor-selection block (search for `NeovimBridge`):

```rust
let bridge: Arc<dyn EditorBridge> = match window_info.app_id.as_str() {
    "nvim" | "neovim" => Arc::new(NeovimBridge::new()),
    "code" | "code-oss" => Arc::new(VSCodeBridge::new()),
    "my-editor" => Arc::new(MyEditorBridge::new()),
    _ => Arc::new(MockEditorBridge::empty()),
};
```

---

## Extension point 5 — Dispatcher tool

Tools are the actions the LLM can request. The registry lives in `crates/yazses-llm/src/tools.rs`; the handlers live in `crates/yazses-core/src/dispatcher.rs`.

### Step 1 — Define the tool in ToolRegistry

Add a `ToolDefinition` to `default_tools()` in `crates/yazses-llm/src/tools.rs`:

```rust
pub fn default_tools() -> Vec<ToolDefinition> {
    vec![
        // ... existing 20 tools ...

        ToolDefinition {
            name: "my_tool",
            description: "One-sentence description shown to the model in its system prompt.",
            parameters: serde_json::json!({
                "type": "object",
                "required": ["arg_one"],
                "properties": {
                    "arg_one": {
                        "type": "string",
                        "description": "What this argument does."
                    }
                }
            }),
        },
    ]
}
```

`ToolDefinition` fields:

| Field | Type | Purpose |
|---|---|---|
| `name` | `&'static str` | Identifier the model emits in its JSON output. Must be unique. The GBNF grammar is rebuilt automatically — hallucinating this name becomes structurally impossible. |
| `description` | `&'static str` | Natural-language description included in the system prompt. |
| `parameters` | `serde_json::Value` | JSON Schema `object` describing the `arguments` map. Used for documentation; per-field grammar constraints are a planned future enhancement. |

The registry test `default_registry_has_20_tools` will fail after this addition — update the count:

```rust
// crates/yazses-llm/src/tools.rs
#[test]
fn default_registry_has_20_tools() {
    let registry = ToolRegistry::default_v1();
    assert_eq!(registry.tools().len(), 21); // update from 20
}
```

### Step 2 — Add a handler in Dispatcher

Add a match arm to `Dispatcher::dispatch()` in `crates/yazses-core/src/dispatcher.rs`:

```rust
"my_tool" => {
    let arg_one = call
        .arguments
        .get("arg_one")
        .and_then(serde_json::Value::as_str)
        .unwrap_or("");
    my_tool_handler(arg_one).await
}
```

Implement the handler as a free function (follow the pattern of the existing OS-action helpers):

```rust
async fn my_tool_handler(arg_one: &str) -> DispatchResult {
    tracing::info!(%arg_one, "my_tool: executing");

    // Do your work here. Use tokio::process::Command for subprocesses,
    // tokio::fs for file I/O, etc.

    DispatchResult::Ok(serde_json::json!({ "ok": true, "arg_one": arg_one }))
}
```

`DispatchResult` variants:

- `DispatchResult::Ok(serde_json::Value)` — success; the value is logged at DEBUG level.
- `DispatchResult::Err(String)` — failure; the error message is logged at WARN level and returned to the IPC caller.

### Step 3 — Write a test

Add a test alongside the existing ones at the bottom of `dispatcher.rs`:

```rust
#[tokio::test]
async fn my_tool_returns_ok() {
    let d = Dispatcher::new(None);
    let r = d
        .dispatch(ToolCall {
            tool: "my_tool".into(),
            arguments: serde_json::json!({ "arg_one": "hello" }),
        })
        .await;
    assert!(r.is_ok());
    let v = r.into_value();
    assert_eq!(v["arg_one"], "hello");
}
```

---

## Cargo feature flags reference

### `yazses-audio`

| Feature | Dependency added | Effect |
|---|---|---|
| `silero` | `ort` (ONNX Runtime, load-dynamic), `ndarray` | Replaces the default RMS gate with Silero VAD v4. Build: `--features yazses-audio/silero` |

### `yazses-stt`

| Feature | Dependency added | Effect |
|---|---|---|
| `moonshine` | `pyo3 0.28` (auto-initialize) | Enables `MoonshineV2Backend` (PyO3 bridge to moonshine-voice; ~9 ms P50 on ≤ 4 s audio). Requires a Python 3.11+ environment with `moonshine-voice` installed. |
| `whisper` | `whisper-rs 0.16` | Enables `WhisperBackend` (whisper.cpp FFI). Requires cmake and a C++ toolchain at build time. |

### `yazses-llm`

| Feature | Dependency added | Effect |
|---|---|---|
| `llama-cpp` | `llama-cpp-2 0.1` | Enables `LlamaCppBackend` (GGUF, prompt caching on LSP prefix). Requires cmake and a C++ toolchain. |
| `ollama` | `reqwest 0.13` | Enables `OllamaBackend` (HTTP client to localhost:11434). Requires a running Ollama daemon. |
| `openai-compatible` | `reqwest 0.13` | Enables `OpenAICompatibleBackend`. **Opt-in only; never compiled by default.** Any key or base URL is user-configured. The zero-egress guarantee is maintained by default; this feature explicitly breaks it. |

### `yazses-inputs`

| Feature | Dependency added | Effect |
|---|---|---|
| `emg` | `serialport 4` | Enables `EmgYespBackend` (USB CDC serial, YESP protocol). Requires a connected device at the configured port. |

### `yazses-editors`

| Feature | Dependency added | Effect |
|---|---|---|
| `neovim` | `nvim-rs 0.9`, `rmpv 1` | Enables `NeovimBridge` (msgpack-RPC via `$NVIM` socket). |
| `vscode` | _(none)_ | Enables `VSCodeBridge` (TCP push to port 57843). No extra dependency; the bridge uses `reqwest` already available via tokio. |
| `hyprland` | `hyprland 0.4.0-beta.3` | Enables `HyprlandWindowDetector` (Linux-only). |
| `sway` | `swayipc 4` | Enables `SwayWindowDetector` (Linux-only). |
| `wlr-toplevel` | `wayland-client 0.31`, `wayland-protocols-wlr 0.3` | Enables `WlrForeignToplevelDetector` (Linux-only). |
| `x11` | `x11rb 0.13` | Enables `X11EwhmWindowDetector` (Linux-only). |

### Typical build configurations

```bash
# Minimal (mock backends only — useful for CI and unit tests)
cargo build --workspace

# Recommended developer build on Linux/Wayland with Neovim
cargo build --workspace \
  --features yazses-stt/whisper,yazses-llm/llama-cpp,yazses-editors/neovim,yazses-editors/hyprland

# With Silero VAD instead of RMS gate
cargo build --workspace \
  --features yazses-audio/silero,yazses-stt/moonshine,yazses-stt/whisper,yazses-llm/llama-cpp

# Ollama instead of llama.cpp (no native build toolchain required)
cargo build --workspace \
  --features yazses-stt/whisper,yazses-llm/ollama

# OpenAI-compatible endpoint (opt-in, breaks zero-egress guarantee)
cargo build --workspace \
  --features yazses-stt/whisper,yazses-llm/openai-compatible
```
