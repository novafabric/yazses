//! Offline LLM reformatting of dictated text via selectable modes.
//!
//! Runs only on the dictation branch of the daemon pipeline, *after* the
//! deterministic disfluency pass and *before* injection. It reuses the
//! already-loaded `Arc<dyn LLMBackend>` (no extra model in memory) and is
//! gated behind output guards plus a latency budget: on disabled/verbatim,
//! empty input, any backend error, timeout, or a failed guard it returns the
//! input text unchanged. With no mode configured (the default), behaviour is
//! byte-identical to a build without this module (adr-011: offline, opt-in).

use std::sync::Arc;
use std::time::Duration;

use crate::protocol::{LLMBackend, LLMOutput, LLMRequest, Role};

/// Reformatting style applied to dictated text. `Verbatim` is the safe default
/// and performs no LLM call.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CleanupMode {
    Verbatim,
    Mechanics,
    Email,
    Notes,
    CodeComment,
    Formal,
}

/// Invariant clause prepended to every non-verbatim mode prompt. This is the
/// core anti-hallucination instruction.
const INVARIANT: &str = "Reformat only. Do not add facts and do not remove \
information. Preserve every proper noun, number, code identifier, and URL \
exactly as given. Output ONLY the reformatted text with no preamble, no \
explanation, and no markdown fences.";

impl CleanupMode {
    /// Parse a mode name (case-insensitive). Returns `None` for unknown names.
    pub fn parse(s: &str) -> Option<Self> {
        match s.trim().to_ascii_lowercase().as_str() {
            "verbatim" => Some(Self::Verbatim),
            "mechanics" => Some(Self::Mechanics),
            "email" => Some(Self::Email),
            "notes" => Some(Self::Notes),
            "code-comment" | "code_comment" | "codecomment" => Some(Self::CodeComment),
            "formal" => Some(Self::Formal),
            _ => None,
        }
    }

    /// System prompt for this mode, or `None` for `Verbatim` (no LLM call).
    pub fn system_prompt(self) -> Option<String> {
        let body = match self {
            Self::Verbatim => return None,
            Self::Mechanics => "Fix capitalization, punctuation, and paragraph \
breaks in the user's dictated text. Do not change any word choices.",
            Self::Email => "Format the user's dictated text as a clear, polite \
email body with appropriate paragraph breaks. Keep the wording faithful.",
            Self::Notes => "Format the user's dictated text as concise notes, \
using bullet points where natural. Keep every fact.",
            Self::CodeComment => "Format the user's dictated text as a clear code \
comment. Preserve all identifiers, symbols, and code tokens verbatim.",
            Self::Formal => "Rewrite the user's dictated text in a formal register \
while preserving its exact meaning and all facts.",
        };
        Some(format!("{INVARIANT}\n\n{body}"))
    }
}

// ── Output guards ───────────────────────────────────────────────────────────

/// True if `output` length is within `[min_ratio, max_ratio]` × `input` length.
/// Empty input always passes (nothing to compare).
fn length_ratio_ok(input: &str, output: &str, min_ratio: f32, max_ratio: f32) -> bool {
    let inlen = input.chars().count();
    if inlen == 0 {
        return true;
    }
    let ratio = output.chars().count() as f32 / inlen as f32;
    ratio >= min_ratio && ratio <= max_ratio
}

/// True if every meaning-critical token from `input` (numbers, code identifiers,
/// URLs) appears as a substring of `output`. Protects against silent drops.
fn tokens_preserved(input: &str, output: &str) -> bool {
    for tok in critical_tokens(input) {
        if !output.contains(&tok) {
            return false;
        }
    }
    true
}

/// Extract tokens that must survive reformatting. Surrounding punctuation is
/// stripped first so the guard checks the bare token (the model may legitimately
/// add a trailing period). A token is meaning-critical when it is a number,
/// identifier, path, URL, version, ALL-CAPS acronym, @mention, #hashtag, or
/// email — the things an LLM reformat must never silently drop or alter.
fn critical_tokens(text: &str) -> Vec<String> {
    text.split_whitespace()
        .map(|w| {
            w.trim_matches(|c: char| {
                matches!(
                    c,
                    ',' | ';' | ':' | '!' | '?' | '.' | '"' | '\'' | '(' | ')' | '[' | ']' | '{' | '}'
                )
            })
        })
        .filter(|w| !w.is_empty() && is_critical(w))
        .map(|w| w.to_string())
        .collect()
}

/// Whether a (punctuation-trimmed) token must be preserved verbatim.
fn is_critical(w: &str) -> bool {
    // @mentions, #hashtags, emails — handles/addresses are easy for an LLM to drop.
    if w.starts_with('@') || w.starts_with('#') || w.contains('@') {
        return true;
    }
    // Numbers, code identifiers, paths, URLs, version strings.
    if w.chars().any(|c| c.is_ascii_digit())
        || w.contains('_')
        || w.contains('/')
        || (w.contains('.') && w.len() > 1)
    {
        return true;
    }
    // ALL-CAPS acronyms of two or more letters (API, URL, NASA) — but not the
    // lone "I"/"A", and only when the whole token is alphabetic.
    let letters: Vec<char> = w.chars().filter(|c| c.is_alphabetic()).collect();
    letters.len() >= 2
        && w.chars().all(|c| c.is_alphabetic())
        && letters.iter().all(|c| c.is_uppercase())
}

// ── Config ────────────────────────────────────────────────────────────────

/// Configuration for the cleanup engine. Defaults preserve current behaviour
/// (disabled, verbatim).
#[derive(Debug, Clone)]
pub struct CleanupConfig {
    pub enabled: bool,
    pub default_mode: CleanupMode,
    /// `(app_id substring, mode)` pairs; first match wins. `app_id` is lowercase.
    pub app_modes: Vec<(String, CleanupMode)>,
    pub max_latency: Duration,
    pub min_length_ratio: f32,
    pub max_length_ratio: f32,
    pub max_tokens: u32,
}

impl Default for CleanupConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            default_mode: CleanupMode::Verbatim,
            app_modes: Vec::new(),
            max_latency: Duration::from_millis(1500),
            min_length_ratio: 0.5,
            max_length_ratio: 2.0,
            max_tokens: 512,
        }
    }
}

impl CleanupConfig {
    /// Build from `YAZSES_CLEANUP_*` env vars (the core has no TOML loader yet).
    /// `YAZSES_CLEANUP_ENABLED=1` enables; `YAZSES_CLEANUP_MODE=<name>` sets the
    /// default mode. Unknown mode names fall back to `Verbatim`.
    pub fn from_env() -> Self {
        let enabled = matches!(
            std::env::var("YAZSES_CLEANUP_ENABLED").ok().as_deref(),
            Some("1") | Some("true")
        );
        let default_mode = std::env::var("YAZSES_CLEANUP_MODE")
            .ok()
            .and_then(|name| CleanupMode::parse(&name))
            .unwrap_or(CleanupMode::Verbatim);
        // `YAZSES_CLEANUP_APP_MODES="thunderbird=email,slack=notes"` overrides the
        // built-in per-app table; unset → sensible defaults.
        let app_modes = std::env::var("YAZSES_CLEANUP_APP_MODES")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .map(|s| parse_app_modes(&s))
            .unwrap_or_else(default_app_modes);
        Self {
            enabled,
            default_mode,
            app_modes,
            ..Self::default()
        }
    }

    /// Resolve the active mode for the focused app: first `app_modes` substring
    /// match (case-insensitive), else `default_mode`.
    pub fn resolve_mode(&self, app_id: Option<&str>) -> CleanupMode {
        if let Some(app) = app_id {
            let app = app.to_ascii_lowercase();
            for (pat, mode) in &self.app_modes {
                if app.contains(pat.as_str()) {
                    return *mode;
                }
            }
        }
        self.default_mode
    }
}

/// Parse `"thunderbird=email,slack=notes,alacritty=verbatim"` into pairs.
/// Unknown modes and empty apps are skipped.
pub fn parse_app_modes(s: &str) -> Vec<(String, CleanupMode)> {
    s.split(',')
        .filter_map(|pair| {
            let (app, mode) = pair.split_once('=')?;
            let app = app.trim().to_ascii_lowercase();
            let mode = CleanupMode::parse(mode)?;
            if app.is_empty() {
                None
            } else {
                Some((app, mode))
            }
        })
        .collect()
}

/// Built-in per-app defaults used when `YAZSES_CLEANUP_APP_MODES` is unset.
/// Substring-matched against the focused window's app id.
fn default_app_modes() -> Vec<(String, CleanupMode)> {
    [
        ("thunderbird", CleanupMode::Email),
        ("mail", CleanupMode::Email),
        ("outlook", CleanupMode::Email),
        ("gmail", CleanupMode::Email),
        ("slack", CleanupMode::Notes),
        ("discord", CleanupMode::Notes),
        ("obsidian", CleanupMode::Notes),
        ("notion", CleanupMode::Notes),
        ("code", CleanupMode::CodeComment),
        ("alacritty", CleanupMode::Verbatim),
        ("kitty", CleanupMode::Verbatim),
        ("term", CleanupMode::Verbatim),
    ]
    .into_iter()
    .map(|(app, mode)| (app.to_string(), mode))
    .collect()
}

// ── Engine ──────────────────────────────────────────────────────────────────

/// Reformats dictated text using a shared LLM backend. Construction is cheap;
/// it holds an `Arc` clone of the daemon's existing backend (no extra model).
pub struct CleanupEngine {
    backend: Arc<dyn LLMBackend>,
    config: CleanupConfig,
}

impl CleanupEngine {
    pub fn new(backend: Arc<dyn LLMBackend>, config: CleanupConfig) -> Self {
        Self { backend, config }
    }

    pub fn config(&self) -> &CleanupConfig {
        &self.config
    }

    /// Reformat `text` in `mode`. NEVER errors — on disabled/verbatim/empty,
    /// any LLM error or timeout, or any failed guard, returns `text` unchanged.
    pub async fn clean(&self, text: &str, mode: CleanupMode) -> String {
        if !self.config.enabled || text.trim().is_empty() {
            return text.to_string();
        }
        let system = match mode.system_prompt() {
            Some(s) => s,
            None => return text.to_string(), // Verbatim
        };

        let req = LLMRequest::builder(system)
            .message(Role::User, text)
            .max_tokens(self.config.max_tokens)
            .temperature(0.0)
            .build();

        let fut = self.backend.complete(req);
        let result = match tokio::time::timeout(self.config.max_latency, fut).await {
            Ok(Ok(out)) => out,
            Ok(Err(_)) | Err(_) => return text.to_string(), // backend error OR timeout
        };

        let cleaned = match result {
            LLMOutput::Text(t) => t,
            LLMOutput::ToolCall(_) => return text.to_string(), // unexpected for cleanup
        };
        let cleaned = cleaned.trim();

        if cleaned.is_empty()
            || !length_ratio_ok(
                text,
                cleaned,
                self.config.min_length_ratio,
                self.config.max_length_ratio,
            )
            || !tokens_preserved(text, cleaned)
        {
            return text.to_string();
        }
        cleaned.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::MockLLMBackend;
    use async_trait::async_trait;
    use serde_json::json;

    #[test]
    fn mode_parses_known_names_case_insensitively() {
        assert_eq!(CleanupMode::parse("verbatim"), Some(CleanupMode::Verbatim));
        assert_eq!(CleanupMode::parse("Email"), Some(CleanupMode::Email));
        assert_eq!(CleanupMode::parse("CODE-COMMENT"), Some(CleanupMode::CodeComment));
        assert_eq!(CleanupMode::parse("code_comment"), Some(CleanupMode::CodeComment));
        assert_eq!(CleanupMode::parse("codecomment"), Some(CleanupMode::CodeComment));
        assert_eq!(CleanupMode::parse("nonsense"), None);
    }

    #[test]
    fn verbatim_has_no_prompt_others_do() {
        assert!(CleanupMode::Verbatim.system_prompt().is_none());
        for m in [
            CleanupMode::Mechanics,
            CleanupMode::Email,
            CleanupMode::Notes,
            CleanupMode::CodeComment,
            CleanupMode::Formal,
        ] {
            let p = m.system_prompt().expect("non-verbatim mode must have a prompt");
            assert!(p.contains("Reformat only"), "mode {m:?} missing invariant");
        }
    }

    #[test]
    fn tokens_preserved_protects_acronyms_mentions_and_emails() {
        // ALL-CAPS acronym dropped → reject.
        assert!(!tokens_preserved("ping the API now", "Ping it now."));
        assert!(tokens_preserved("ping the API now", "Ping the API now."));
        // @mention dropped → reject; preserved → ok.
        assert!(!tokens_preserved("tell @alice today", "Tell her today."));
        assert!(tokens_preserved("tell @alice today", "Tell @alice today."));
        // email dropped → reject.
        assert!(!tokens_preserved("mail bob@x.io now", "Mail him now."));
        // #hashtag preserved.
        assert!(tokens_preserved("post #launch today", "Post #launch today."));
        // lone "I"/"A" and ordinary words are NOT treated as critical.
        assert!(tokens_preserved("I went to a store", "I went to a store."));
    }

    #[test]
    fn parse_app_modes_reads_pairs_and_skips_garbage() {
        let m = parse_app_modes("Thunderbird=email, slack=notes , bad=nope, =email, term=verbatim");
        assert_eq!(m.len(), 3);
        assert_eq!(m[0], ("thunderbird".to_string(), CleanupMode::Email));
        assert_eq!(m[1], ("slack".to_string(), CleanupMode::Notes));
        assert_eq!(m[2], ("term".to_string(), CleanupMode::Verbatim));
    }

    #[test]
    fn default_app_modes_resolve_through_config() {
        let cfg = CleanupConfig {
            app_modes: default_app_modes(),
            default_mode: CleanupMode::Mechanics,
            ..CleanupConfig::default()
        };
        assert_eq!(cfg.resolve_mode(Some("org.mozilla.Thunderbird")), CleanupMode::Email);
        assert_eq!(cfg.resolve_mode(Some("Alacritty")), CleanupMode::Verbatim);
        assert_eq!(cfg.resolve_mode(Some("FirefoxNightly")), CleanupMode::Mechanics); // falls through
    }

    #[test]
    fn length_ratio_rejects_too_short_and_too_long() {
        let input = "abcdefghijklmnopqrst"; // 20
        assert!(length_ratio_ok(input, "abcdefghijklmno", 0.5, 2.0)); // 15 ok
        assert!(!length_ratio_ok(input, "abcde", 0.5, 2.0)); // 5 too short
        assert!(!length_ratio_ok(input, &"x".repeat(50), 0.5, 2.0)); // 50 too long
    }

    #[test]
    fn length_ratio_handles_empty_input() {
        assert!(length_ratio_ok("", "", 0.5, 2.0));
        assert!(length_ratio_ok("", "hello", 0.5, 2.0));
    }

    #[test]
    fn tokens_preserved_detects_dropped_number_and_identifier() {
        assert!(tokens_preserved("deploy v2.3 to prod at 0900", "Deploy v2.3 to prod at 0900."));
        // dropped the time "0900"
        assert!(!tokens_preserved("deploy at 0900", "Deploy."));
        // dropped a code identifier "snake_case_fn"
        assert!(!tokens_preserved("call snake_case_fn now", "Call it now."));
        // preserved a URL
        assert!(tokens_preserved("see https://x.io/a", "See https://x.io/a"));
        assert!(!tokens_preserved("see https://x.io/a", "See the link."));
    }

    #[test]
    fn config_default_is_disabled_and_verbatim() {
        let c = CleanupConfig::default();
        assert!(!c.enabled);
        assert_eq!(c.default_mode, CleanupMode::Verbatim);
        assert_eq!(c.min_length_ratio, 0.5);
        assert_eq!(c.max_length_ratio, 2.0);
        assert_eq!(c.max_latency.as_millis(), 1500);
    }

    #[test]
    fn config_resolve_mode_uses_app_then_default() {
        let c = CleanupConfig {
            enabled: true,
            default_mode: CleanupMode::Verbatim,
            app_modes: vec![("thunderbird".into(), CleanupMode::Email)],
            ..CleanupConfig::default()
        };
        assert_eq!(c.resolve_mode(Some("thunderbird")), CleanupMode::Email);
        assert_eq!(c.resolve_mode(Some("firefox")), CleanupMode::Verbatim);
        assert_eq!(c.resolve_mode(None), CleanupMode::Verbatim);
    }

    fn engine_with(output: &str, mode: CleanupMode, enabled: bool) -> CleanupEngine {
        let cfg = CleanupConfig {
            enabled,
            default_mode: mode,
            ..CleanupConfig::default()
        };
        CleanupEngine::new(Arc::new(MockLLMBackend::text(output)), cfg)
    }

    #[tokio::test]
    async fn clean_returns_llm_output_on_happy_path() {
        let eng = engine_with("Hello, world.", CleanupMode::Mechanics, true);
        let out = eng.clean("hello world", CleanupMode::Mechanics).await;
        assert_eq!(out, "Hello, world.");
    }

    #[tokio::test]
    async fn clean_skips_llm_when_verbatim() {
        let eng = engine_with("MUTATED", CleanupMode::Verbatim, true);
        let out = eng.clean("keep me exactly", CleanupMode::Verbatim).await;
        assert_eq!(out, "keep me exactly");
    }

    #[tokio::test]
    async fn clean_skips_llm_when_disabled() {
        let eng = engine_with("MUTATED", CleanupMode::Mechanics, false);
        let out = eng.clean("keep me exactly", CleanupMode::Mechanics).await;
        assert_eq!(out, "keep me exactly");
    }

    #[tokio::test]
    async fn clean_falls_back_when_token_dropped() {
        // LLM drops the number "0900" → guard rejects → input returned.
        let eng = engine_with("Deploy to prod.", CleanupMode::Mechanics, true);
        let out = eng.clean("deploy to prod at 0900", CleanupMode::Mechanics).await;
        assert_eq!(out, "deploy to prod at 0900");
    }

    #[tokio::test]
    async fn clean_falls_back_on_empty_output() {
        let eng = engine_with("   ", CleanupMode::Mechanics, true);
        let out = eng.clean("some real text here", CleanupMode::Mechanics).await;
        assert_eq!(out, "some real text here");
    }

    /// Backend that sleeps longer than the cleanup budget, to exercise timeout.
    struct SlowBackend;

    #[async_trait]
    impl LLMBackend for SlowBackend {
        fn name(&self) -> &str {
            "slow"
        }
        async fn complete(&self, _req: LLMRequest) -> anyhow::Result<LLMOutput> {
            tokio::time::sleep(Duration::from_millis(200)).await;
            Ok(LLMOutput::Text("too late".into()))
        }
    }

    #[tokio::test]
    async fn clean_falls_back_on_timeout() {
        let cfg = CleanupConfig {
            enabled: true,
            default_mode: CleanupMode::Mechanics,
            max_latency: Duration::from_millis(20), // shorter than the 200ms sleep
            ..CleanupConfig::default()
        };
        let eng = CleanupEngine::new(Arc::new(SlowBackend), cfg);
        let out = eng.clean("preserve this text", CleanupMode::Mechanics).await;
        assert_eq!(out, "preserve this text");
    }

    #[tokio::test]
    async fn clean_falls_back_on_tool_call_output() {
        let cfg = CleanupConfig { enabled: true, default_mode: CleanupMode::Mechanics, ..CleanupConfig::default() };
        let eng = CleanupEngine::new(
            Arc::new(MockLLMBackend::tool_call("type_text", json!({"text": "x"}))),
            cfg,
        );
        let out = eng.clean("preserve this exactly", CleanupMode::Mechanics).await;
        assert_eq!(out, "preserve this exactly");
    }

    #[tokio::test]
    async fn clean_falls_back_when_output_too_long() {
        // input is ~16 chars; mock returns ~94 chars (>2x) → length guard rejects.
        let long = "this is a very long reformatted output that greatly exceeds twice the input length for sure yes";
        let eng = engine_with(long, CleanupMode::Mechanics, true);
        let out = eng.clean("short input here", CleanupMode::Mechanics).await;
        assert_eq!(out, "short input here");
    }

    #[tokio::test]
    async fn enabled_email_mode_reformats_when_guards_pass() {
        let cfg = CleanupConfig {
            enabled: true,
            default_mode: CleanupMode::Email,
            ..CleanupConfig::default()
        };
        let eng = CleanupEngine::new(
            Arc::new(MockLLMBackend::text("Hi team,\n\nWe are shipping at 0900.\n\nThanks")),
            cfg,
        );
        let mode = eng.config().resolve_mode(None);
        // Input long enough that the email-formatted output stays within the
        // length-ratio guard (≤ 2.0×); the time token must survive.
        let out = eng.clean("team we are shipping at 0900 thanks", mode).await;
        assert!(out.contains("0900")); // token preserved → not rejected
        assert!(out.starts_with("Hi team"));
    }
}
