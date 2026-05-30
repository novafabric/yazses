// YazSes daemon orchestrator — Phase 5: full pipeline wiring.
//
// Pipeline (adr-001, 07_architecture.md):
//   InputBackend → (hold_start) → AudioCapture + EditorBridge
//   → (hold_end)  → VadGate → STTRouter → LLM → Dispatcher
//   → IDLE
//
// Backends are feature-selected at startup; the daemon carries no direct
// knowledge of which concrete type is used — only the trait objects matter.

use std::sync::Arc;

use anyhow::Context;
use serde::Serialize;
use serde_json::{json, Value};
use tokio::sync::{broadcast, mpsc, Mutex};
use tracing::{debug, info, warn};

use yazses_audio::{AudioCapture, AudioFrame};
use yazses_editors::{EditorBridge, MockEditorBridge, NullWindowDetector, WindowDetector};
use yazses_inputs::{HotKey, InputBackend, InputEvent as HwInputEvent, KeyboardHoldBackend};
use yazses_ipc::{handler, IpcServer, Request};
use yazses_llm::{
    apply_dictation_commands, polish_mechanics, CleanupConfig, CleanupEngine, LLMBackend,
    LLMOutput, LLMRequest, MockLLMBackend, Role, ToolRegistry, Vocabulary,
};
#[cfg(feature = "ollama")]
use yazses_llm::OllamaBackend;
use yazses_memory::{MockEmbedder, PersonalMemory};
#[cfg(feature = "whisper")]
use yazses_stt::WhisperBackend;
use yazses_stt::{MockSTTBackend, STTBackend, STTRouter, TranscribeOptions};

use crate::config;
use crate::dispatcher::Dispatcher;
use crate::state::{DaemonEvent, DaemonState};

// ── LatencyTracker ────────────────────────────────────────────────────────────

struct LatencyTracker {
    samples: std::collections::VecDeque<u64>, // milliseconds
}

impl LatencyTracker {
    fn new() -> Self {
        Self {
            samples: std::collections::VecDeque::with_capacity(100),
        }
    }

    fn record(&mut self, ms: u64) {
        if self.samples.len() >= 100 {
            self.samples.pop_front();
        }
        self.samples.push_back(ms);
    }

    fn p50(&self) -> Option<u64> {
        percentile(&self.samples, 50)
    }

    fn p95(&self) -> Option<u64> {
        percentile(&self.samples, 95)
    }
}

fn percentile(samples: &std::collections::VecDeque<u64>, p: usize) -> Option<u64> {
    if samples.is_empty() {
        return None;
    }
    let mut sorted: Vec<u64> = samples.iter().copied().collect();
    sorted.sort_unstable();
    let idx = (sorted.len() * p / 100).min(sorted.len() - 1);
    Some(sorted[idx])
}

// ── SharedState ───────────────────────────────────────────────────────────────

struct SharedState {
    state: DaemonState,
    started_at: std::time::Instant,
    last_error: Option<String>,
    model_name: String,
    hotkey: String,
    platform_name: String,
    streaming_enabled: bool,
    commands_enabled: bool,
    remote_connected: bool,
    latency: LatencyTracker,
    turn_count: u64,
    /// Live mic level (mean(|samples|)) of the latest audio frame while
    /// recording; 0.0 otherwise. Drives the voice-activity overlay.
    audio_level: f32,
    /// VAD gate the overlay normalises against (mirrors accessibility.vad_threshold).
    vad_threshold: f32,
}

impl SharedState {
    fn new() -> Self {
        Self {
            state: DaemonState::Loading,
            started_at: std::time::Instant::now(),
            last_error: None,
            model_name: "moonshine-v2-small-streaming".into(),
            hotkey: "right_alt".into(),
            platform_name: std::env::consts::OS.into(),
            streaming_enabled: false,
            commands_enabled: true,
            remote_connected: false,
            latency: LatencyTracker::new(),
            turn_count: 0,
            audio_level: 0.0,
            vad_threshold: 0.01,
        }
    }

    fn apply(&mut self, event: DaemonEvent) {
        match self.state.apply(&event) {
            Ok(next) => {
                if next != self.state {
                    info!(from = %self.state, to = %next, "state transition");
                    self.state = next;
                }
                if let DaemonEvent::ErrorOccurred { ref message } = event {
                    self.last_error = Some(message.clone());
                }
                if matches!(event, DaemonEvent::ErrorResolved) {
                    self.last_error = None;
                }
            }
            Err(e) => warn!("{e}"),
        }
    }
}

/// Status response shape — v0.4-compatible exactly (adr-010).
#[derive(Serialize)]
struct StatusResponse {
    state: String,
    model: String,
    hotkey: String,
    injection_backend: Option<String>,
    last_error: Option<String>,
    uptime_s: f64,
    platform: String,
    streaming_enabled: bool,
    commands_enabled: bool,
    remote_connected: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    latency_p50_ms: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    latency_p95_ms: Option<u64>,
    turn_count: u64,
    // For the voice-activity overlay (yazses-overlay) — parity with the Python daemon.
    audio_level: f32,
    vad_threshold: f32,
}

// ── Pipeline ──────────────────────────────────────────────────────────────────

/// Holds all runtime backends.  Constructed once at daemon startup.
struct Pipeline {
    stt: Arc<STTRouter>,
    llm: Arc<dyn LLMBackend>,
    editor: Arc<dyn EditorBridge>,
    window: Arc<dyn WindowDetector>,
    dispatcher: Arc<Dispatcher>,
    /// LLM reformatting of dictated text, reusing the same `llm` backend.
    cleanup: Arc<CleanupEngine>,
    /// User dictionary: biases STT and post-corrects recognized tokens.
    vocabulary: Vocabulary,
    /// Rewrite spoken "new line"/"open paren"/… in dictated text (opt-in).
    dictation_commands_enabled: bool,
    /// Deterministic capitalization/punctuation polish on the no-LLM path (opt-in).
    mechanics_enabled: bool,
    #[allow(dead_code)]
    tool_grammar: String,
    /// Moonshine transcriber for the streaming polling loop (None if not compiled in).
    #[cfg(feature = "moonshine")]
    moonshine: Option<Arc<yazses_stt::MoonshineV2Backend>>,
}

impl Pipeline {
    fn build(memory: Option<Arc<PersonalMemory>>) -> Self {
        // STT: select backend based on feature flags and YAZSES_STT_MODEL env var.
        let longform: Arc<dyn STTBackend> = {
            #[cfg(feature = "whisper")]
            {
                let model_path = std::env::var("YAZSES_STT_MODEL")
                    .unwrap_or_else(|_| {
                        let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".into());
                        format!("{home}/.cache/huggingface/hub/whisper.cpp/ggml-base.bin")
                    });
                match WhisperBackend::new(&model_path) {
                    Ok(b) => {
                        info!(%model_path, "Whisper STT backend loaded");
                        Arc::new(b) as Arc<dyn STTBackend>
                    }
                    Err(e) => {
                        warn!("Whisper backend init failed ({e}); falling back to mock STT");
                        Arc::new(MockSTTBackend::new("longform-mock", "")) as Arc<dyn STTBackend>
                    }
                }
            }
            #[cfg(not(feature = "whisper"))]
            Arc::new(MockSTTBackend::new("longform-mock", ""))
        };
        // Moonshine: fast streaming STT for short utterances (≤ 4 s).
        // Load once as a typed Arc; shared with the streaming poll loop below.
        #[cfg(feature = "moonshine")]
        let moonshine_shared: Option<Arc<yazses_stt::MoonshineV2Backend>> = {
            let model_name = std::env::var("YAZSES_MOONSHINE_MODEL")
                .unwrap_or_else(|_| "tiny-en".into());
            match yazses_stt::MoonshineV2Backend::new(&model_name) {
                Ok(b) => {
                    info!(%model_name, "Moonshine STT backend loaded");
                    Some(Arc::new(b))
                }
                Err(e) => {
                    warn!("Moonshine backend init failed ({e}); using mock for short utterances");
                    None
                }
            }
        };
        let streaming: Arc<dyn STTBackend> = {
            #[cfg(feature = "moonshine")]
            {
                if let Some(ref m) = moonshine_shared {
                    m.clone() as Arc<dyn STTBackend>
                } else {
                    Arc::new(MockSTTBackend::new("streaming-mock", "")) as Arc<dyn STTBackend>
                }
            }
            #[cfg(not(feature = "moonshine"))]
            Arc::new(MockSTTBackend::new("streaming-mock", ""))
        };
        // Route: short audio (≤ 4 s) → Moonshine, longer → Whisper.
        // If Moonshine is absent, force threshold to 0 so everything goes to Whisper.
        #[cfg(all(feature = "whisper", not(feature = "moonshine")))]
        let stt = Arc::new(STTRouter::new(streaming, longform, 0.0));
        #[cfg(not(all(feature = "whisper", not(feature = "moonshine"))))]
        let stt = Arc::new(STTRouter::with_default_threshold(streaming, longform));

        // LLM: use OllamaBackend when `ollama` feature is compiled in,
        // otherwise fall back to mock (type_text pass-through, v0.4 behaviour).
        let llm: Arc<dyn LLMBackend> = {
            #[cfg(feature = "ollama")]
            {
                let model = std::env::var("YAZSES_LLM_MODEL")
                    .unwrap_or_else(|_| "qwen2.5:1.5b".into());
                match OllamaBackend::new(model) {
                    Ok(b) => Arc::new(b),
                    Err(e) => {
                        warn!("Ollama backend init failed ({e}); falling back to mock");
                        Arc::new(MockLLMBackend::text(""))
                    }
                }
            }
            #[cfg(not(feature = "ollama"))]
            Arc::new(MockLLMBackend::text(""))
        };

        // Editor: no active $NVIM socket in default config.
        let editor: Arc<dyn EditorBridge> = Arc::new(MockEditorBridge::empty());
        let window: Arc<dyn WindowDetector> = Arc::new(NullWindowDetector);

        // Tool registry + GBNF grammar (adr-004).
        let registry = ToolRegistry::default_v1();
        let tool_grammar = registry.grammar().to_owned();

        let dispatcher = Arc::new(Dispatcher::new(memory));

        // Cleanup engine reuses the SAME loaded LLM backend (no extra model).
        let cleanup = Arc::new(CleanupEngine::new(llm.clone(), CleanupConfig::from_env()));

        // Deterministic dictation post-processing (env-configured; off by default
        // so the default pipeline stays byte-identical).
        let vocabulary = Vocabulary::from_env();
        let dictation_commands_enabled = matches!(
            std::env::var("YAZSES_DICTATION_COMMANDS").ok().as_deref(),
            Some("1") | Some("true")
        );
        let mechanics_enabled = matches!(
            std::env::var("YAZSES_MECHANICS").ok().as_deref(),
            Some("1") | Some("true")
        );

        // Reuse the already-loaded Moonshine instance for the streaming poll loop.
        #[cfg(feature = "moonshine")]
        let moonshine_handle: Option<Arc<yazses_stt::MoonshineV2Backend>> = moonshine_shared;

        Self {
            stt,
            llm,
            editor,
            window,
            dispatcher,
            cleanup,
            vocabulary,
            dictation_commands_enabled,
            mechanics_enabled,
            tool_grammar,
            #[cfg(feature = "moonshine")]
            moonshine: moonshine_handle,
        }
    }

    /// Deterministic, model-free post-processing for dictated text: apply the
    /// user vocabulary (always — a no-op when empty), spoken formatting commands
    /// (opt-in), and capitalization/punctuation polish (opt-in). Runs after any
    /// LLM cleanup, before injection.
    fn postprocess_dictation(&self, text: &str) -> String {
        let mut out = self.vocabulary.correct(text);
        out = apply_dictation_commands(&out, self.dictation_commands_enabled);
        if self.mechanics_enabled {
            out = polish_mechanics(&out);
        }
        out
    }

    /// Process one utterance: PCM audio → transcript → LLM → dispatch.
    /// `turn_start` is the instant the hold-end was received (PCM delivered).
    async fn process_utterance(
        &self,
        pcm: Vec<f32>,
        sample_rate: u32,
        shared: &Mutex<SharedState>,
        turn_start: std::time::Instant,
        already_injected: Option<Arc<tokio::sync::Mutex<String>>>,
    ) {
        // Empty PCM means capture failed — skip STT and return to IDLE.
        if pcm.is_empty() {
            let mut s = shared.lock().await;
            s.apply(DaemonEvent::HoldEnd);           // Recording → Transcribing
            s.apply(DaemonEvent::ErrorOccurred {     // Transcribing → Error
                message: "audio capture produced no samples".into(),
            });
            s.apply(DaemonEvent::ErrorResolved);     // Error → Idle
            return;
        }

        // Recording → Transcribing
        shared.lock().await.apply(DaemonEvent::HoldEnd);

        // Query editor context (parallel with future audio steps).
        let editor_ctx = self.editor.get_context().await.ok().flatten();
        // Bias STT with editor LSP context AND the user vocabulary so jargon and
        // proper nouns transcribe correctly (the lever Aqua/Wispr lean on).
        let mut prompt_parts: Vec<String> = Vec::new();
        if let Some(p) = editor_ctx.as_ref().map(|c| c.to_initial_prompt(224)) {
            prompt_parts.push(p);
        }
        if let Some(hint) = self.vocabulary.prompt_hint() {
            prompt_parts.push(hint);
        }
        let initial_prompt = if prompt_parts.is_empty() {
            None
        } else {
            Some(prompt_parts.join(" "))
        };

        // STT
        let opts = TranscribeOptions {
            initial_prompt,
            language: None,
        };
        let transcript = match self.stt.transcribe(&pcm, sample_rate, opts).await {
            Ok(t) => t.text,
            Err(e) => {
                warn!("STT error: {e}");
                shared.lock().await.apply(DaemonEvent::ErrorOccurred {
                    message: e.to_string(),
                });
                return;
            }
        };
        debug!(%transcript, "STT result");

        // Signal transcript ready (stays in Transcribing per state machine).
        shared.lock().await.apply(DaemonEvent::TranscriptReady {
            text: transcript.clone(),
        });

        if transcript.trim().is_empty() {
            // Nothing to inject — cancel via noop tool call to reach Idle.
            shared.lock().await.apply(DaemonEvent::ToolCallReady {
                tool: json!({"tool": "cancel_request", "arguments": {}}),
            });
            let elapsed_ms = turn_start.elapsed().as_millis() as u64;
            let mut s = shared.lock().await;
            s.latency.record(elapsed_ms);
            s.turn_count += 1;
            s.apply(DaemonEvent::DispatchComplete);
            return;
        }

        // Build LLM request. System prompt instructs the model to classify
        // the utterance and return a JSON tool call. Grammar constraint is
        // passed for llama.cpp; Ollama ignores it but uses the prompt.
        let system = r#"You are YazSes, a voice dictation and command agent.

The user spoke a voice utterance. Decide whether it is:
1. DICTATION — something to type (default for most speech)
2. A COMMAND — an OS/editor action like open file, git commit, etc.

Always respond with ONLY a JSON object on a single line. No prose. No markdown.

For dictation (most common):
{"tool":"type_text","arguments":{"text":"<exact words spoken>"}}

For commands, use the matching tool:
{"tool":"open_file","arguments":{"path":"<path>"}}
{"tool":"git_commit","arguments":{"message":"<msg>"}}
{"tool":"commit_to_memory","arguments":{"content":"<text>","source":"voice"}}
{"tool":"recall","arguments":{"query":"<query>"}}
{"tool":"cancel_request","arguments":{}}

When in doubt, use type_text."#;

        let mut builder = LLMRequest::builder(system).message(Role::User, &transcript);
        if let Some(ctx) = &editor_ctx {
            builder = builder.editor_context(ctx.to_llm_block());
        }
        let llm_req = builder.build();

        let output = match self.llm.complete(llm_req).await {
            Ok(o) => o,
            Err(e) => {
                // LLM failed — fall back to typing the raw transcript directly.
                warn!("LLM error ({e}); falling back to type_text with raw transcript");
                LLMOutput::Text(transcript.clone())
            }
        };

        let call = match output {
            LLMOutput::ToolCall(c) => {
                info!(tool = %c.tool, "LLM tool call");
                c
            }
            LLMOutput::Text(text) => {
                // Plain text → type_text (dictation mode).
                info!(%text, "LLM plain text → type_text");
                yazses_llm::ToolCall {
                    tool: "type_text".into(),
                    arguments: json!({"text": text}),
                }
            }
        };

        // LLM cleanup: only on dictation (type_text), only when streaming has not
        // already injected partial text (streaming + cleanup are mutually exclusive
        // in v1), and only when enabled. Always falls back to the raw text.
        let call = if call.tool == "type_text" && self.cleanup.config().enabled {
            let already = match &already_injected {
                Some(arc) => !arc.lock().await.is_empty(),
                None => false,
            };
            if already {
                call // streaming path owns the text; skip cleanup
            } else {
                let raw = call
                    .arguments
                    .get("text")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                let app_id = self
                    .window
                    .focused_window()
                    .await
                    .ok()
                    .flatten()
                    .map(|w| w.app_id);
                let mode = self.cleanup.config().resolve_mode(app_id.as_deref());
                let cleaned = self.cleanup.clean(&raw, mode).await;
                if cleaned == raw {
                    call
                } else {
                    info!(mode = ?mode, "cleanup reformatted dictation");
                    yazses_llm::ToolCall {
                        tool: "type_text".into(),
                        arguments: json!({ "text": cleaned }),
                    }
                }
            }
        } else {
            call
        };

        // Deterministic dictation post-processing (vocabulary correction, spoken
        // formatting commands, mechanics polish). No-op by default. Skipped when
        // streaming already owns the injected text.
        let streaming_owns = match &already_injected {
            Some(arc) => !arc.lock().await.is_empty(),
            None => false,
        };
        let call = if call.tool == "type_text" && !streaming_owns {
            let raw = call
                .arguments
                .get("text")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let processed = self.postprocess_dictation(&raw);
            if processed == raw {
                call
            } else {
                yazses_llm::ToolCall {
                    tool: "type_text".into(),
                    arguments: json!({ "text": processed }),
                }
            }
        } else {
            call
        };

        // Reconcile against whatever the streaming poll loop already injected.
        let call = if call.tool == "type_text" {
            if let Some(ai_arc) = &already_injected {
                let injected = ai_arc.lock().await.clone();
                if !injected.is_empty() {
                    let full = call.arguments.get("text")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string();
                    match new_words_suffix(&injected, &full) {
                        Some(ref suffix) if suffix.is_empty() => {
                            // Streaming already injected everything — nothing to add.
                            shared.lock().await.apply(DaemonEvent::ToolCallReady {
                                tool: json!({"tool": "cancel_request", "arguments": {}}),
                            });
                            let elapsed_ms = turn_start.elapsed().as_millis() as u64;
                            let mut s = shared.lock().await;
                            s.latency.record(elapsed_ms);
                            s.turn_count += 1;
                            s.apply(DaemonEvent::DispatchComplete);
                            return;
                        }
                        Some(suffix) => {
                            // Streaming got the prefix right — only inject the new tail.
                            yazses_llm::ToolCall {
                                tool: "type_text".into(),
                                arguments: json!({"text": suffix}),
                            }
                        }
                        None => {
                            // Transcripts diverged — erase wrong streaming text, then inject full.
                            // +1 for the trailing space that inject_text always appends.
                            let erase_n = injected.chars().count() + 1;
                            crate::dispatcher::erase_chars(erase_n).await;
                            call
                        }
                    }
                } else {
                    call
                }
            } else {
                call
            }
        } else {
            call
        };

        // For commands (non-type_text) the streaming loop may have already typed
        // partial text on screen (e.g. "open new folder").  Erase it before the
        // command executes so it fires into a clean focused window.
        if call.tool != "type_text" && call.tool != "cancel_request" {
            if let Some(ai_arc) = &already_injected {
                let injected = ai_arc.lock().await.clone();
                if !injected.is_empty() {
                    let erase_n = injected.chars().count() + 1; // +1 for trailing space
                    crate::dispatcher::erase_chars(erase_n).await;
                }
            }
        }

        shared.lock().await.apply(DaemonEvent::ToolCallReady {
            tool: json!({"tool": &call.tool, "arguments": &call.arguments}),
        });
        let result = self.dispatcher.dispatch(call).await;
        debug!(?result, "dispatch result");

        let elapsed_ms = turn_start.elapsed().as_millis() as u64;
        let mut s = shared.lock().await;
        s.latency.record(elapsed_ms);
        s.turn_count += 1;
        s.apply(DaemonEvent::DispatchComplete);
    }
}

// ── Daemon ────────────────────────────────────────────────────────────────────

pub struct Daemon {
    shared: Arc<Mutex<SharedState>>,
    shutdown_tx: broadcast::Sender<()>,
}

impl Daemon {
    pub fn new() -> Self {
        let (shutdown_tx, _) = broadcast::channel(1);
        Self {
            shared: Arc::new(Mutex::new(SharedState::new())),
            shutdown_tx,
        }
    }

    async fn start_ipc(
        &self,
        memory: Option<Arc<PersonalMemory>>,
    ) -> anyhow::Result<Arc<IpcServer>> {
        let socket_path = config::socket_path();
        let server = Arc::new(IpcServer::new(&socket_path));

        // status
        {
            let shared = self.shared.clone();
            server
                .register(
                    "status",
                    handler!(move |_req: Request| {
                        let shared = shared.clone();
                        async move {
                            let s = shared.lock().await;
                            let uptime = s.started_at.elapsed().as_secs_f64();
                            let resp = StatusResponse {
                                state: s.state.to_string(),
                                model: s.model_name.clone(),
                                hotkey: s.hotkey.clone(),
                                injection_backend: None,
                                last_error: s.last_error.clone(),
                                uptime_s: (uptime * 100.0).round() / 100.0,
                                platform: s.platform_name.clone(),
                                streaming_enabled: s.streaming_enabled,
                                commands_enabled: s.commands_enabled,
                                remote_connected: s.remote_connected,
                                latency_p50_ms: s.latency.p50(),
                                latency_p95_ms: s.latency.p95(),
                                turn_count: s.turn_count,
                                audio_level: (s.audio_level * 1_000_000.0).round() / 1_000_000.0,
                                vad_threshold: s.vad_threshold,
                            };
                            Ok(serde_json::to_value(resp)?)
                        }
                    }),
                )
                .await;
        }

        // shutdown
        {
            let tx = self.shutdown_tx.clone();
            server
                .register(
                    "shutdown",
                    handler!(move |_req: Request| {
                        let tx = tx.clone();
                        async move {
                            tx.send(()).ok();
                            Ok(json!({"ok": true}))
                        }
                    }),
                )
                .await;
        }

        // inject (manual text injection)
        {
            let shared = self.shared.clone();
            server
                .register(
                    "inject",
                    handler!(move |req: Request| {
                        let shared = shared.clone();
                        async move {
                            let text = req
                                .params
                                .get("text")
                                .and_then(Value::as_str)
                                .unwrap_or("")
                                .to_string();
                            if text.is_empty() {
                                return Ok(json!({"ok": false, "reason": "empty text"}));
                            }
                            let s = shared.lock().await;
                            if s.state == DaemonState::Loading {
                                return Ok(json!({"ok": false, "reason": "daemon still loading"}));
                            }
                            drop(s);
                            info!(%text, "inject");
                            let result = crate::dispatcher::inject_text(&text).await;
                            Ok(result.into_value())
                        }
                    }),
                )
                .await;
        }

        // ── Memory IPC handlers ───────────────────────────────────────────────

        {
            let mem = memory.clone();
            server
                .register(
                    "memory_commit",
                    handler!(move |req: Request| {
                        let mem = mem.clone();
                        async move {
                            let Some(m) = mem else {
                                return Ok(
                                    json!({"ok": false, "reason": "memory not initialised"}),
                                );
                            };
                            let content = req
                                .params
                                .get("content")
                                .and_then(Value::as_str)
                                .unwrap_or("")
                                .to_string();
                            let source = req
                                .params
                                .get("source")
                                .and_then(Value::as_str)
                                .unwrap_or("manual")
                                .to_string();
                            match m.commit(&content, &source, None, &[], 0).await {
                                Ok(id) => Ok(json!({"ok": true, "rowid": id})),
                                Err(e) => Ok(json!({"ok": false, "reason": e.to_string()})),
                            }
                        }
                    }),
                )
                .await;
        }

        {
            let mem = memory.clone();
            server
                .register(
                    "memory_recall",
                    handler!(move |req: Request| {
                        let mem = mem.clone();
                        async move {
                            let Some(m) = mem else {
                                return Ok(
                                    json!({"ok": false, "reason": "memory not initialised"}),
                                );
                            };
                            let query = req
                                .params
                                .get("query")
                                .and_then(Value::as_str)
                                .unwrap_or("")
                                .to_string();
                            let k = req.params.get("limit").and_then(Value::as_u64).unwrap_or(5)
                                as usize;
                            match m.recall(&query, k).await {
                                Ok(recs) => {
                                    let items: Vec<Value> = recs
                                        .into_iter()
                                        .map(|r| {
                                            json!({
                                                "transcript": r.transcript,
                                                "source": r.source,
                                                "distance": r.distance,
                                            })
                                        })
                                        .collect();
                                    Ok(json!({"ok": true, "results": items}))
                                }
                                Err(e) => Ok(json!({"ok": false, "reason": e.to_string()})),
                            }
                        }
                    }),
                )
                .await;
        }

        {
            let mem = memory.clone();
            server
                .register(
                    "memory_forget",
                    handler!(move |req: Request| {
                        let mem = mem.clone();
                        async move {
                            let Some(m) = mem else {
                                return Ok(
                                    json!({"ok": false, "reason": "memory not initialised"}),
                                );
                            };
                            let minutes = req
                                .params
                                .get("minutes")
                                .and_then(Value::as_u64)
                                .unwrap_or(5);
                            match m.forget_last(minutes).await {
                                Ok(n) => Ok(json!({"ok": true, "deleted": n})),
                                Err(e) => Ok(json!({"ok": false, "reason": e.to_string()})),
                            }
                        }
                    }),
                )
                .await;
        }

        // ── Passthrough stubs ─────────────────────────────────────────────────
        server.register("remote_start", handler!(move |_req: Request| async {
            Ok(json!({"ok": false, "reason": "remote forwarding not yet implemented (Phase 6)"}))
        })).await;
        server.register("remote_stop", handler!(move |_req: Request| async {
            Ok(json!({"ok": false, "reason": "remote forwarding not yet implemented (Phase 6)"}))
        })).await;
        server
            .register(
                "remote_status",
                handler!(move |_req: Request| async { Ok(json!({"connected": false})) }),
            )
            .await;
        server.register("enroll_start", handler!(move |_req: Request| async {
            Ok(json!({"ok": false, "reason": "enrollment wizard not yet implemented (Phase 6)"}))
        })).await;

        {
            let shared = self.shared.clone();
            server
                .register(
                    "streaming_enable",
                    handler!(move |_req: Request| {
                        let shared = shared.clone();
                        async move {
                            shared.lock().await.streaming_enabled = true;
                            Ok(json!({"ok": true}))
                        }
                    }),
                )
                .await;
        }
        {
            let shared = self.shared.clone();
            server
                .register(
                    "streaming_disable",
                    handler!(move |_req: Request| {
                        let shared = shared.clone();
                        async move {
                            shared.lock().await.streaming_enabled = false;
                            Ok(json!({"ok": true}))
                        }
                    }),
                )
                .await;
        }

        server.clone().serve().await?;
        Ok(server)
    }

    pub async fn run(self) -> anyhow::Result<()> {
        info!("YazSes daemon v{} starting", env!("CARGO_PKG_VERSION"));

        // Personal memory — opens in-memory for default dev build.
        // Production: open at config::memory_db_path() with KeyManager.
        let memory = Arc::new(
            PersonalMemory::open_in_memory(Arc::new(MockEmbedder))
                .context("opening personal memory")?,
        );

        let _ipc = self
            .start_ipc(Some(memory.clone()))
            .await
            .context("starting IPC server")?;

        // PID file
        let pid_path = config::pid_path();
        if let Some(parent) = pid_path.parent() {
            tokio::fs::create_dir_all(parent).await.ok();
        }
        tokio::fs::write(&pid_path, std::process::id().to_string())
            .await
            .with_context(|| format!("writing PID file {}", pid_path.display()))?;

        // Build pipeline
        let pipeline = Arc::new(Pipeline::build(Some(memory)));

        // Keyboard hold backend — Right Alt by default, configurable via YAZSES_HOTKEY.
        let hotkey: HotKey = std::env::var("YAZSES_HOTKEY")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(HotKey::RightAlt);
        let (kbd_tx, mut kbd_rx) = mpsc::channel::<HwInputEvent>(32);
        let mut keyboard = KeyboardHoldBackend::new(hotkey, 200);
        if let Err(e) = keyboard.start(kbd_tx).await {
            warn!("keyboard backend failed to start: {e}");
        }

        // Finished utterances (PCM + sample_rate) come back from the recording task.
        let (utt_tx, mut utt_rx) = mpsc::channel::<(Vec<f32>, u32)>(4);

        // Stop-recording signal channel. Replaced on each new HoldStart.
        let mut stop_tx: Option<tokio::sync::oneshot::Sender<()>> = None;
        // Streaming poll loop cancel channel and already-injected tracker.
        let mut stream_stop_tx: Option<tokio::sync::oneshot::Sender<()>> = None;
        let mut current_already_injected: Option<Arc<tokio::sync::Mutex<String>>> = None;

        self.shared.lock().await.apply(DaemonEvent::ModelsLoaded);
        info!("YazSes daemon ready — hold Right Alt to dictate");

        let mut shutdown_rx = self.shutdown_tx.subscribe();
        loop {
            tokio::select! {
                _ = shutdown_rx.recv() => {
                    info!("shutdown requested via IPC");
                    break;
                }
                _ = tokio::signal::ctrl_c() => {
                    info!("SIGINT received; shutting down");
                    break;
                }

                // Keyboard events from evdev
                Some(ev) = kbd_rx.recv() => {
                    match ev {
                        HwInputEvent::HoldStart { leaked, .. } => {
                            if stop_tx.is_some() {
                                // Already recording — ignore duplicate
                            } else {
                                let (stx, srx) = tokio::sync::oneshot::channel::<()>();
                                stop_tx = Some(stx);

                                let stream_buf = Arc::new(tokio::sync::Mutex::new(Vec::<f32>::new()));
                                let already_inj = Arc::new(tokio::sync::Mutex::new(String::new()));
                                current_already_injected = Some(already_inj.clone());

                                #[cfg(feature = "moonshine")]
                                if let Some(ref moon) = pipeline.moonshine {
                                    let (sstx, ssrx) = tokio::sync::oneshot::channel::<()>();
                                    stream_stop_tx = Some(sstx);
                                    tokio::spawn(streaming_poll_loop(
                                        moon.clone(),
                                        stream_buf.clone(),
                                        ssrx,
                                        500,
                                        already_inj.clone(),
                                    ));
                                }

                                let utt_tx2 = utt_tx.clone();
                                let buf2 = stream_buf;
                                let shared_lvl = Arc::clone(&self.shared);
                                tokio::spawn(async move {
                                    record_until_stop(srx, utt_tx2, buf2, shared_lvl).await;
                                });
                                self.shared.lock().await
                                    .apply(DaemonEvent::HoldStart { leaked });
                                info!("hold start — recording");
                            }
                        }
                        HwInputEvent::HoldEnd { .. } => {
                            if let Some(tx) = stop_tx.take() {
                                let _ = tx.send(());
                                info!("hold end — awaiting transcription");
                            }
                            if let Some(tx) = stream_stop_tx.take() {
                                let _ = tx.send(());
                            }
                        }
                        _ => {}
                    }
                }

                // Finished utterance from recording task
                Some((pcm, sample_rate)) = utt_rx.recv() => {
                    let p = Arc::clone(&pipeline);
                    let shared = Arc::clone(&self.shared);
                    let turn_start = std::time::Instant::now();
                    let ai = current_already_injected.take();
                    tokio::spawn(async move {
                        p.process_utterance(pcm, sample_rate, &shared, turn_start, ai).await;
                    });
                }
            }
        }

        tokio::fs::remove_file(&pid_path).await.ok();
        info!("YazSes daemon stopped");
        Ok(())
    }
}

impl Default for Daemon {
    fn default() -> Self {
        Self::new()
    }
}

// ── Recording task ────────────────────────────────────────────────────────────

/// Capture microphone audio until the stop signal fires, then send the PCM buffer.
async fn record_until_stop(
    mut stop_rx: tokio::sync::oneshot::Receiver<()>,
    utt_tx: mpsc::Sender<(Vec<f32>, u32)>,
    stream_buf: Arc<tokio::sync::Mutex<Vec<f32>>>,
    shared: Arc<tokio::sync::Mutex<SharedState>>,
) {
    let (atx, mut arx) = mpsc::channel::<AudioFrame>(512);
    let mut cap = AudioCapture::new(16_000);
    if let Err(e) = cap.start(atx) {
        warn!("audio capture start failed: {e}");
        let _ = stop_rx.await;
        let _ = utt_tx.send((vec![], 16_000)).await;
        return;
    }

    let mut pcm: Vec<f32> = Vec::new();
    let mut sample_rate = 16_000u32;

    loop {
        tokio::select! {
            _ = &mut stop_rx => break,
            Some(frame) = arx.recv() => {
                sample_rate = frame.sample_rate;
                // Publish live mic level for the overlay (mean(|samples|)).
                if !frame.samples.is_empty() {
                    let sum: f32 = frame.samples.iter().map(|s| s.abs()).sum();
                    shared.lock().await.audio_level = sum / frame.samples.len() as f32;
                }
                stream_buf.lock().await.extend(&frame.samples);
                pcm.extend(frame.samples);
            }
        }
    }

    cap.stop();
    shared.lock().await.audio_level = 0.0; // recording done — overlay calms down
    while let Ok(frame) = arx.try_recv() {
        stream_buf.lock().await.extend(&frame.samples);
        pcm.extend(frame.samples);
    }

    let n_samples = pcm.len();
    let duration_ms = n_samples as u64 * 1000 / sample_rate as u64;
    info!(n_samples, duration_ms, "utterance captured");

    if n_samples > 0 {
        let _ = utt_tx.send((pcm, sample_rate)).await;
    }
}

/// Poll Moonshine every `interval_ms` while the user holds the hotkey.
///
/// Two mechanisms prevent the "erases text it just typed" failure mode:
///
/// 1. **Stability gate** — a word is only injected once it appears at the same
///    position in *two consecutive ticks*.  Moonshine revises earlier words as
///    audio grows; requiring stability across ticks filters that drift.
///
/// 2. **Command suppression** — if the partial transcript looks like a voice
///    command ("open …", "git …", etc.) the loop stays silent and lets the
///    final Whisper + LLM pipeline decide.  This prevents "open new folder"
///    from being typed on screen while also triggering an open_file tool call.
#[cfg(feature = "moonshine")]
async fn streaming_poll_loop(
    moonshine: Arc<yazses_stt::MoonshineV2Backend>,
    stream_buf: Arc<tokio::sync::Mutex<Vec<f32>>>,
    mut stop_rx: tokio::sync::oneshot::Receiver<()>,
    interval_ms: u64,
    already_injected: Arc<tokio::sync::Mutex<String>>,
) {
    use tokio::time::{interval, Duration};
    let mut tick = interval(Duration::from_millis(interval_ms));
    tick.tick().await; // skip the immediate first tick

    // Previous tick's transcript — used to compute the stable prefix.
    let mut prev_transcript = String::new();

    info!("streaming poll loop started");
    loop {
        tokio::select! {
            _ = &mut stop_rx => break,
            _ = tick.tick() => {
                let audio: Vec<f32> = stream_buf.lock().await.clone();
                if audio.len() < 16_000 { continue; } // < 1 s — too short

                // Run Moonshine in a dedicated blocking thread so Tokio's
                // async runtime threads stay available during inference.
                let m = moonshine.clone();
                let text = match tokio::task::spawn_blocking(move || {
                    m.transcribe_sync(&audio).ok().map(|t| t.text)
                }).await {
                    Ok(Some(t)) => t.trim().to_string(),
                    _ => continue,
                };
                if text.is_empty() { continue; }
                info!(%text, "streaming poll tick");

                // Suppress injection for command-like utterances; the full
                // pipeline will classify and execute them correctly.
                if looks_like_command(&text) {
                    prev_transcript = text;
                    info!("streaming poll: command-like utterance, suppressing inject");
                    continue;
                }

                // Stability gate: accept only words that appeared at the same
                // position in the previous tick AND this tick.
                let stable = longest_stable_prefix(&prev_transcript, &text);
                prev_transcript = text;
                if stable.is_empty() { continue; }

                // Find new stable words beyond what was already on screen.
                let already_snap = already_injected.lock().await.clone();
                let new_words = match new_words_suffix(&already_snap, &stable) {
                    Some(w) if !w.is_empty() => w,
                    _ => continue,
                };

                let ok = crate::dispatcher::stream_inject_text(&new_words).await;
                info!(%new_words, ok, "streaming poll: inject result");
                if ok {
                    // Record the full stable prefix so suffix detection
                    // stays accurate on the next tick.
                    *already_injected.lock().await = stable;
                }
            }
        }
    }
}

/// Strip punctuation and lowercase a word for fuzzy comparison.
fn norm_word(w: &str) -> String {
    w.chars()
        .filter(|c| c.is_alphabetic() || c.is_numeric())
        .collect::<String>()
        .to_lowercase()
}

#[cfg(feature = "moonshine")]
/// Longest prefix of `curr` whose words match `prev` word-for-word (normalised).
/// Used for stability gating: a word only graduates to "stable" when Moonshine
/// placed it at the same position across two consecutive ticks.
fn longest_stable_prefix(prev: &str, curr: &str) -> String {
    let prev_words: Vec<&str> = prev.split_whitespace().collect();
    let curr_words: Vec<&str> = curr.split_whitespace().collect();
    let n = prev_words
        .iter()
        .zip(curr_words.iter())
        .take_while(|(p, c)| norm_word(p) == norm_word(c))
        .count();
    curr_words[..n].join(" ")
}

#[cfg(feature = "moonshine")]
/// Heuristic: does the partial transcript look like a voice command?
///
/// If so, the streaming loop suppresses text injection and lets the final
/// Whisper + LLM pipeline decide whether to type or execute a tool call.
/// Better to wait 400 ms than to type "open new folder" on screen when
/// the user wanted to open a folder.
fn looks_like_command(text: &str) -> bool {
    let t = text.trim().to_lowercase();
    let prefixes = [
        "open ", "close ", "git ", "commit ",
        "screenshot", "set volume", "volume ",
        "focus ", "launch ", "switch mode",
        "set timer", "timer ", "note ", "quick note",
        "remember ", "recall ", "forget ",
        "play pause", "dismiss", "cancel",
    ];
    prefixes.iter().any(|p| t.starts_with(p))
}

/// Word-level suffix comparison.
///
/// - `Some(words)` — `full` extends `already`; `words` is what comes after (may be empty if equal).
/// - `None` — the transcripts diverged; caller should erase streaming text and re-inject.
fn new_words_suffix(already: &str, full: &str) -> Option<String> {
    let already_words: Vec<&str> = already.split_whitespace().collect();
    let full_words: Vec<&str> = full.split_whitespace().collect();
    if already_words.is_empty() {
        return Some(full_words.join(" "));
    }
    if full_words.len() < already_words.len() {
        return None; // full is shorter — regression, treat as diverged
    }
    let prefix_ok = full_words[..already_words.len()]
        .iter()
        .zip(already_words.iter())
        .all(|(a, b)| norm_word(a) == norm_word(b));
    if prefix_ok {
        Some(full_words[already_words.len()..].join(" "))
    } else {
        None // diverged
    }
}
