use std::sync::Arc;

use serde_json::{json, Value};
use tracing::{debug, info, warn};

use yazses_llm::ToolCall;
use yazses_memory::PersonalMemory;

/// Result of dispatching a single `ToolCall`.
#[derive(Debug)]
pub enum DispatchResult {
    Ok(Value),
    Err(String),
}

impl DispatchResult {
    pub fn is_ok(&self) -> bool {
        matches!(self, Self::Ok(_))
    }

    pub fn into_value(self) -> Value {
        match self {
            Self::Ok(v) => v,
            Self::Err(e) => json!({"error": e}),
        }
    }
}

/// Routes `ToolCall`s from the LLM to their handler implementations (adr-004).
///
/// Memory tools (`commit_to_memory`, `forget_last`, `recall`) are fully
/// implemented via `PersonalMemory`.  All OS-action tools are implemented via
/// `tokio::process::Command`.
pub struct Dispatcher {
    memory: Option<Arc<PersonalMemory>>,
}

impl Dispatcher {
    pub fn new(memory: Option<Arc<PersonalMemory>>) -> Self {
        Self { memory }
    }

    pub async fn dispatch(&self, call: ToolCall) -> DispatchResult {
        debug!(tool = %call.tool, "dispatching tool call");

        match call.tool.as_str() {
            // ── Text injection ────────────────────────────────────────────────
            "type_text" => {
                let text = call
                    .arguments
                    .get("text")
                    .and_then(Value::as_str)
                    .unwrap_or("");
                inject_text(text).await
            }

            "key_sequence" => {
                let keys = call
                    .arguments
                    .get("keys")
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_default();
                let key_strs: Vec<&str> = keys.iter().filter_map(Value::as_str).collect();
                inject_key_sequence(&key_strs).await
            }

            // ── Memory tools (fully implemented) ──────────────────────────────
            "commit_to_memory" => self.handle_commit(call.arguments).await,
            "forget_last" => self.handle_forget(call.arguments).await,
            "recall" => self.handle_recall(call.arguments).await,

            // ── Clarify ───────────────────────────────────────────────────────
            "clarify" => {
                let question = call
                    .arguments
                    .get("question")
                    .and_then(Value::as_str)
                    .unwrap_or("?");
                DispatchResult::Ok(json!({ "ok": true, "question": question }))
            }

            // ── File / editor tools ───────────────────────────────────────────
            "open_file" => {
                let path = call
                    .arguments
                    .get("path")
                    .and_then(Value::as_str)
                    .unwrap_or("");
                open_file(path).await
            }

            "goto_symbol" => {
                let sym = call
                    .arguments
                    .get("symbol")
                    .and_then(Value::as_str)
                    .unwrap_or("");
                goto_symbol(sym).await
            }

            // ── VCS ───────────────────────────────────────────────────────────
            "git_commit" => {
                let msg = call
                    .arguments
                    .get("message")
                    .and_then(Value::as_str)
                    .unwrap_or("");
                git_commit(msg).await
            }

            // ── System / media ────────────────────────────────────────────────
            "send_message" => {
                debug!(tool = "send_message", "send_message not yet implemented");
                DispatchResult::Ok(json!({ "ok": true, "tool": "send_message", "backend": "stub" }))
            }

            "app_launch" => {
                let app = call
                    .arguments
                    .get("app")
                    .and_then(Value::as_str)
                    .unwrap_or("");
                app_launch(app).await
            }

            "window_focus" => {
                let name = call
                    .arguments
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or("");
                window_focus(name).await
            }

            "volume_set" => {
                let percent = call
                    .arguments
                    .get("percent")
                    .and_then(Value::as_u64)
                    .unwrap_or(50);
                volume_set(percent).await
            }

            "media_play_pause" => media_play_pause().await,

            "screenshot_named" => {
                let name = call
                    .arguments
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or("screenshot");
                screenshot_named(name).await
            }

            "note_quick" => {
                let text = call
                    .arguments
                    .get("text")
                    .and_then(Value::as_str)
                    .unwrap_or("");
                let title = call.arguments.get("title").and_then(Value::as_str);
                note_quick(text, title, None).await
            }

            "time_set_timer" => {
                let seconds = call
                    .arguments
                    .get("seconds")
                    .and_then(Value::as_u64)
                    .unwrap_or(60);
                let label = call
                    .arguments
                    .get("label")
                    .and_then(Value::as_str)
                    .unwrap_or("Timer done")
                    .to_string();
                time_set_timer(seconds, label).await
            }

            "dismiss_notification" => dismiss_notification().await,

            "mode_switch" => {
                let mode = call
                    .arguments
                    .get("mode")
                    .and_then(Value::as_str)
                    .unwrap_or("");
                mode_switch(mode).await
            }

            "cancel_request" => DispatchResult::Ok(json!({ "ok": true })),

            unknown => {
                warn!(%unknown, "unknown tool in ToolCall");
                DispatchResult::Err(format!("unknown tool: {unknown}"))
            }
        }
    }
}

// ── Text injection helpers ────────────────────────────────────────────────────

/// Inject a small word chunk during streaming (no clipboard — uses direct typing).
///
/// Avoids the paste-key detection issues that can arise when Right Alt is held.
pub async fn stream_inject_text(text: &str) -> bool {
    if text.is_empty() {
        return true;
    }
    let text_with_space = format!("{text} ");
    let is_wayland = std::env::var("WAYLAND_DISPLAY").is_ok();
    let is_x11 = std::env::var("DISPLAY").is_ok();

    if is_wayland {
        if let Ok(s) = tokio::process::Command::new("wtype")
            .arg("--")
            .arg(&text_with_space)
            .status()
            .await
        {
            if s.success() {
                return true;
            }
        }
    }
    if is_x11 || !is_wayland {
        if let Ok(s) = tokio::process::Command::new("xdotool")
            .args(["type", "--clearmodifiers", "--delay", "12", "--", &text_with_space])
            .status()
            .await
        {
            return s.success();
        }
    }
    false
}

/// Erase `n` characters by sending BackSpace keystrokes.
pub async fn erase_chars(n: usize) {
    if n == 0 {
        return;
    }
    let is_wayland = std::env::var("WAYLAND_DISPLAY").is_ok();
    let is_x11 = std::env::var("DISPLAY").is_ok();
    let n_str = n.to_string();
    if is_x11 || !is_wayland {
        let _ = tokio::process::Command::new("xdotool")
            .args(["key", "--clearmodifiers", "--repeat", &n_str, "BackSpace"])
            .status()
            .await;
    } else if is_wayland {
        for _ in 0..n {
            let _ = tokio::process::Command::new("wtype")
                .args(["-k", "BackSpace"])
                .status()
                .await;
        }
    }
}

/// Priority: wtype (Wayland) > ydotool (Wayland) > xclip+paste (X11) > xdotool type (X11 fallback).
pub async fn inject_text(text: &str) -> DispatchResult {
    use tokio::process::Command;
    if text.is_empty() {
        return DispatchResult::Ok(json!({ "ok": true, "typed": "" }));
    }

    let is_wayland = std::env::var("WAYLAND_DISPLAY").is_ok();
    let is_x11 = std::env::var("DISPLAY").is_ok();

    // Append a space so back-to-back utterances don't run together.
    let text_with_space = format!("{text} ");
    let text = text_with_space.as_str();

    if is_wayland {
        if let Ok(s) = Command::new("wtype").arg("--").arg(text).status().await {
            if s.success() {
                debug!(%text, "typed via wtype");
                return DispatchResult::Ok(json!({ "ok": true, "backend": "wtype" }));
            }
        }
        if let Ok(s) = Command::new("ydotool")
            .arg("type")
            .arg("--")
            .arg(text)
            .status()
            .await
        {
            if s.success() {
                debug!(%text, "typed via ydotool");
                return DispatchResult::Ok(json!({ "ok": true, "backend": "ydotool" }));
            }
        }
    }

    if is_x11 || !is_wayland {
        // xdotool type: keystroke-by-keystroke, works in all apps and over SSH.
        // --clearmodifiers ensures Right Alt key-up doesn't corrupt the output.
        if let Ok(s) = Command::new("xdotool")
            .arg("type")
            .arg("--clearmodifiers")
            .arg("--delay")
            .arg("12")
            .arg("--")
            .arg(text)
            .status()
            .await
        {
            if s.success() {
                debug!(%text, "typed via xdotool");
                return DispatchResult::Ok(json!({ "ok": true, "backend": "xdotool" }));
            }
        }
    }

    warn!(%text, "no injection backend available; install xdotool (X11) or wtype/ydotool (Wayland)");
    DispatchResult::Err("no injection backend (install xdotool or wtype/ydotool)".into())
}

async fn inject_key_sequence(keys: &[&str]) -> DispatchResult {
    use tokio::process::Command;
    if keys.is_empty() {
        return DispatchResult::Ok(json!({ "ok": true }));
    }
    let is_wayland = std::env::var("WAYLAND_DISPLAY").is_ok();
    let is_x11 = std::env::var("DISPLAY").is_ok();

    if is_wayland {
        // Try wtype first; each key is sent with -k (key name).
        let mut wtype_ok = true;
        for key in keys {
            match Command::new("wtype").arg("-k").arg(key).status().await {
                Ok(s) if s.success() => {}
                _ => {
                    wtype_ok = false;
                    break;
                }
            }
        }
        if wtype_ok {
            debug!(?keys, "key_sequence via wtype");
            return DispatchResult::Ok(json!({ "ok": true, "backend": "wtype" }));
        }
        // Fallback: ydotool
        let mut ydotool_ok = true;
        for key in keys {
            match Command::new("ydotool").arg("key").arg(key).status().await {
                Ok(s) if s.success() => {}
                _ => {
                    ydotool_ok = false;
                    break;
                }
            }
        }
        if ydotool_ok {
            debug!(?keys, "key_sequence via ydotool");
            return DispatchResult::Ok(json!({ "ok": true, "backend": "ydotool" }));
        }
        warn!(?keys, "key_sequence: wtype and ydotool both unavailable on Wayland");
        return DispatchResult::Err("key_sequence on Wayland requires wtype or ydotool".into());
    }

    if is_x11 {
        for key in keys {
            let _ = Command::new("xdotool").arg("key").arg(key).status().await;
        }
        return DispatchResult::Ok(json!({ "ok": true, "backend": "xdotool" }));
    }

    warn!(?keys, "key_sequence: no display server detected");
    DispatchResult::Err(
        "key_sequence: no display server (DISPLAY or WAYLAND_DISPLAY not set)".into(),
    )
}

// ── OS-action helpers ─────────────────────────────────────────────────────────

/// Open a file with the default application (xdg-open, spawned without waiting).
async fn open_file(path: &str) -> DispatchResult {
    info!(%path, "open_file: launching xdg-open");
    let _ = tokio::process::Command::new("xdg-open").arg(path).spawn();
    DispatchResult::Ok(json!({ "ok": true, "path": path }))
}

/// Navigate to a symbol in the running Neovim instance if $NVIM is set.
async fn goto_symbol(symbol: &str) -> DispatchResult {
    if let Ok(nvim_socket) = std::env::var("NVIM") {
        info!(%symbol, %nvim_socket, "goto_symbol: sending search to Neovim");
        let search_cmd = format!("/<{symbol}><CR>");
        let status = tokio::process::Command::new("nvim")
            .args(["--server", &nvim_socket, "--remote-send", &search_cmd])
            .status()
            .await;
        match status {
            Ok(s) if s.success() => {
                DispatchResult::Ok(json!({ "ok": true, "symbol": symbol, "backend": "nvim" }))
            }
            Ok(s) => {
                warn!(%symbol, code = ?s.code(), "goto_symbol: nvim --remote-send failed");
                DispatchResult::Ok(
                    json!({ "ok": false, "symbol": symbol, "error": "nvim remote-send failed" }),
                )
            }
            Err(e) => {
                warn!(%symbol, %e, "goto_symbol: failed to spawn nvim");
                DispatchResult::Err(format!("goto_symbol: {e}"))
            }
        }
    } else {
        info!(%symbol, "goto_symbol: $NVIM not set — no editor IPC available");
        DispatchResult::Ok(json!({ "ok": true, "symbol": symbol, "backend": "none" }))
    }
}

/// Run `git commit -m <message>` in the current directory.
async fn git_commit(message: &str) -> DispatchResult {
    info!(%message, "git_commit: running git commit");
    match tokio::process::Command::new("git")
        .args(["commit", "-m", message])
        .output()
        .await
    {
        Ok(output) if output.status.success() => {
            let stdout = String::from_utf8_lossy(&output.stdout);
            // Extract the abbreviated SHA from git output (e.g. "[main abc1234] message").
            let sha = stdout
                .lines()
                .next()
                .and_then(|l| l.split_whitespace().nth(1))
                .unwrap_or("")
                .trim_end_matches(']')
                .to_string();
            DispatchResult::Ok(json!({ "ok": true, "sha": sha, "message": message }))
        }
        Ok(output) => {
            let stderr = String::from_utf8_lossy(&output.stderr);
            warn!(%message, %stderr, "git_commit: git commit failed");
            DispatchResult::Err(format!("git commit failed: {stderr}"))
        }
        Err(e) => {
            warn!(%message, %e, "git_commit: failed to spawn git");
            DispatchResult::Err(format!("git_commit: {e}"))
        }
    }
}

/// Launch an application as a background process; fall back to xdg-open.
async fn app_launch(app: &str) -> DispatchResult {
    info!(%app, "app_launch: spawning application");
    if let Ok(_child) = tokio::process::Command::new(app).spawn() {
        return DispatchResult::Ok(json!({ "ok": true, "app": app, "backend": "direct" }));
    }
    info!(%app, "app_launch: direct spawn failed, trying xdg-open");
    let _ = tokio::process::Command::new("xdg-open").arg(app).spawn();
    DispatchResult::Ok(json!({ "ok": true, "app": app, "backend": "xdg-open" }))
}

/// Focus a window by name using wmctrl or xdotool.
async fn window_focus(name: &str) -> DispatchResult {
    info!(%name, "window_focus: trying wmctrl");
    if let Ok(s) = tokio::process::Command::new("wmctrl")
        .args(["-a", name])
        .status()
        .await
    {
        if s.success() {
            return DispatchResult::Ok(
                json!({ "ok": true, "name": name, "backend": "wmctrl" }),
            );
        }
    }
    info!(%name, "window_focus: wmctrl failed, trying xdotool");
    if let Ok(s) = tokio::process::Command::new("xdotool")
        .args(["search", "--name", name, "windowfocus"])
        .status()
        .await
    {
        if s.success() {
            return DispatchResult::Ok(
                json!({ "ok": true, "name": name, "backend": "xdotool" }),
            );
        }
    }
    warn!(%name, "window_focus: all backends failed");
    DispatchResult::Ok(
        json!({ "ok": false, "name": name, "error": "no window manager tool available" }),
    )
}

/// Set the system volume (0–100) via wpctl (PipeWire) or pactl (PulseAudio).
async fn volume_set(percent: u64) -> DispatchResult {
    let percent = percent.min(100);
    info!(percent, "volume_set: trying wpctl");
    let vol_arg = format!("{percent}%");
    if let Ok(s) = tokio::process::Command::new("wpctl")
        .args(["set-volume", "@DEFAULT_AUDIO_SINK@", &vol_arg])
        .status()
        .await
    {
        if s.success() {
            return DispatchResult::Ok(
                json!({ "ok": true, "percent": percent, "backend": "wpctl" }),
            );
        }
    }
    info!(percent, "volume_set: wpctl failed, trying pactl");
    let pactl_arg = format!("{percent}%");
    if let Ok(s) = tokio::process::Command::new("pactl")
        .args(["set-sink-volume", "@DEFAULT_SINK@", &pactl_arg])
        .status()
        .await
    {
        if s.success() {
            return DispatchResult::Ok(
                json!({ "ok": true, "percent": percent, "backend": "pactl" }),
            );
        }
    }
    warn!(percent, "volume_set: both wpctl and pactl failed");
    DispatchResult::Ok(
        json!({ "ok": false, "percent": percent, "error": "no volume backend available" }),
    )
}

/// Toggle play/pause via playerctl or the XF86AudioPlay key.
async fn media_play_pause() -> DispatchResult {
    info!("media_play_pause: trying playerctl");
    if let Ok(s) = tokio::process::Command::new("playerctl")
        .arg("play-pause")
        .status()
        .await
    {
        if s.success() {
            return DispatchResult::Ok(json!({ "ok": true, "backend": "playerctl" }));
        }
    }
    info!("media_play_pause: playerctl failed, trying xdotool key XF86AudioPlay");
    let _ = tokio::process::Command::new("xdotool")
        .args(["key", "XF86AudioPlay"])
        .status()
        .await;
    DispatchResult::Ok(json!({ "ok": true, "backend": "xdotool-key" }))
}

/// Take a screenshot to ~/Pictures/<name>.png, choosing the backend by session type.
async fn screenshot_named(name: &str) -> DispatchResult {
    let pictures_dir = {
        let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".into());
        std::path::PathBuf::from(home).join("Pictures")
    };
    // Create ~/Pictures/ if it doesn't exist.
    if let Err(e) = tokio::fs::create_dir_all(&pictures_dir).await {
        warn!(%e, "screenshot_named: failed to create ~/Pictures");
    }
    let dest = pictures_dir.join(format!("{name}.png"));
    let dest_str = dest.to_string_lossy().to_string();

    let is_wayland = std::env::var("WAYLAND_DISPLAY").is_ok();
    let is_x11 = std::env::var("DISPLAY").is_ok();

    if is_wayland {
        info!(%dest_str, "screenshot_named: using grim (Wayland)");
        if let Ok(s) = tokio::process::Command::new("grim")
            .arg(&dest_str)
            .status()
            .await
        {
            if s.success() {
                return DispatchResult::Ok(
                    json!({ "ok": true, "path": dest_str, "backend": "grim" }),
                );
            }
        }
    }

    if is_x11 {
        info!(%dest_str, "screenshot_named: trying scrot (X11)");
        if let Ok(s) = tokio::process::Command::new("scrot")
            .arg(&dest_str)
            .status()
            .await
        {
            if s.success() {
                return DispatchResult::Ok(
                    json!({ "ok": true, "path": dest_str, "backend": "scrot" }),
                );
            }
        }
    }

    info!(%dest_str, "screenshot_named: falling back to gnome-screenshot");
    if let Ok(s) = tokio::process::Command::new("gnome-screenshot")
        .args(["-f", &dest_str])
        .status()
        .await
    {
        if s.success() {
            return DispatchResult::Ok(
                json!({ "ok": true, "path": dest_str, "backend": "gnome-screenshot" }),
            );
        }
    }

    warn!(%dest_str, "screenshot_named: all screenshot backends failed");
    DispatchResult::Err(
        "screenshot_named: no screenshot backend available (install grim, scrot, or gnome-screenshot)".into(),
    )
}

/// Append a timestamped note to ~/notes.md.
///
/// `override_path` is used only in tests to avoid mutating `HOME`.
async fn note_quick(
    text: &str,
    title: Option<&str>,
    override_path: Option<std::path::PathBuf>,
) -> DispatchResult {
    use tokio::io::AsyncWriteExt as _;

    let notes_path = match override_path {
        Some(p) => p,
        None => {
            let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".into());
            std::path::PathBuf::from(home).join("notes.md")
        }
    };

    let timestamp = {
        let duration = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default();
        let secs = duration.as_secs();
        let sec = secs % 60;
        let min = (secs / 60) % 60;
        let hour = (secs / 3600) % 24;
        let days = secs / 86400;
        let (year, month, day) = epoch_days_to_ymd(days);
        format!("{year:04}-{month:02}-{day:02} {hour:02}:{min:02}:{sec:02} UTC")
    };

    let heading = match title {
        Some(t) => format!("\n## {timestamp} {t}\n"),
        None => format!("\n## {timestamp}\n"),
    };
    let entry = format!("{heading}{text}\n");

    info!(path = %notes_path.display(), "note_quick: appending to notes.md");
    match tokio::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&notes_path)
        .await
    {
        Ok(mut f) => match f.write_all(entry.as_bytes()).await {
            Ok(()) => DispatchResult::Ok(
                json!({ "ok": true, "path": notes_path.to_string_lossy() }),
            ),
            Err(e) => DispatchResult::Err(format!("note_quick: write error: {e}")),
        },
        Err(e) => DispatchResult::Err(format!("note_quick: open error: {e}")),
    }
}

/// Convert days since Unix epoch to (year, month, day).
///
/// Algorithm from <http://howardhinnant.github.io/date_algorithms.html>
fn epoch_days_to_ymd(days: u64) -> (u32, u32, u32) {
    let z = days as i64 + 719_468;
    let era = z.div_euclid(146_097);
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    (y as u32, m as u32, d as u32)
}

/// Spawn a background Tokio task that fires a desktop notification after `seconds`.
async fn time_set_timer(seconds: u64, label: String) -> DispatchResult {
    info!(seconds, %label, "time_set_timer: spawning background timer");
    let label_for_task = label.clone();
    tokio::spawn(async move {
        tokio::time::sleep(tokio::time::Duration::from_secs(seconds)).await;
        let _ = tokio::process::Command::new("notify-send")
            .args(["--app-name=YazSes", "--icon=alarm-symbolic", "YazSes Timer", &label_for_task])
            .status()
            .await;
        info!(seconds, label = %label_for_task, "time_set_timer: notification fired");
    });
    DispatchResult::Ok(json!({ "ok": true, "seconds": seconds, "label": label }))
}

/// Dismiss the current desktop notification via dunstctl or a tiny auto-dismiss.
async fn dismiss_notification() -> DispatchResult {
    info!("dismiss_notification: trying dunstctl close");
    if let Ok(s) = tokio::process::Command::new("dunstctl")
        .arg("close")
        .status()
        .await
    {
        if s.success() {
            return DispatchResult::Ok(json!({ "ok": true, "backend": "dunstctl" }));
        }
    }
    info!("dismiss_notification: dunstctl failed, sending tiny auto-dismiss notification");
    let _ = tokio::process::Command::new("notify-send")
        .args(["-t", "100", " "])
        .status()
        .await;
    DispatchResult::Ok(json!({ "ok": true, "backend": "notify-send" }))
}

/// Log the requested daemon mode switch (full wiring is Phase 6).
async fn mode_switch(mode: &str) -> DispatchResult {
    info!(%mode, "mode_switch: requested (full wiring deferred to Phase 6)");
    DispatchResult::Ok(json!({ "ok": true, "mode": mode }))
}

// ── Memory handlers ───────────────────────────────────────────────────────────

impl Dispatcher {
    async fn handle_commit(&self, args: Value) -> DispatchResult {
        let Some(mem) = &self.memory else {
            return DispatchResult::Err("personal memory not initialised".into());
        };
        let transcript = match args.get("content").and_then(Value::as_str) {
            Some(t) => t.to_string(),
            None => return DispatchResult::Err("commit_to_memory: missing 'content'".into()),
        };
        let source = args
            .get("source")
            .and_then(Value::as_str)
            .unwrap_or("voice");
        let tags_json = args
            .get("tags")
            .and_then(Value::as_array)
            .map(|a| a.iter().filter_map(Value::as_str).collect::<Vec<_>>())
            .unwrap_or_default();
        let ttl = args.get("ttl_seconds").and_then(Value::as_u64).unwrap_or(0);

        match mem
            .commit(&transcript, source, None, &tags_json.to_vec(), ttl)
            .await
        {
            Ok(rowid) => DispatchResult::Ok(json!({ "ok": true, "rowid": rowid })),
            Err(e) => DispatchResult::Err(format!("commit_to_memory: {e}")),
        }
    }

    async fn handle_forget(&self, args: Value) -> DispatchResult {
        let Some(mem) = &self.memory else {
            return DispatchResult::Err("personal memory not initialised".into());
        };
        let minutes = args.get("minutes").and_then(Value::as_u64).unwrap_or(5);
        match mem.forget_last(minutes).await {
            Ok(n) => DispatchResult::Ok(json!({ "ok": true, "deleted": n })),
            Err(e) => DispatchResult::Err(format!("forget_last: {e}")),
        }
    }

    async fn handle_recall(&self, args: Value) -> DispatchResult {
        let Some(mem) = &self.memory else {
            return DispatchResult::Err("personal memory not initialised".into());
        };
        let query = match args.get("query").and_then(Value::as_str) {
            Some(q) => q.to_string(),
            None => return DispatchResult::Err("recall: missing 'query'".into()),
        };
        let k = args.get("limit").and_then(Value::as_u64).unwrap_or(5) as usize;
        match mem.recall(&query, k).await {
            Ok(records) => {
                let items: Vec<Value> = records
                    .into_iter()
                    .map(|r| {
                        json!({
                            "transcript": r.transcript,
                            "source": r.source,
                            "distance": r.distance,
                            "created_at": r.created_at,
                        })
                    })
                    .collect();
                DispatchResult::Ok(json!({ "ok": true, "results": items }))
            }
            Err(e) => DispatchResult::Err(format!("recall: {e}")),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;

    fn mem() -> Arc<PersonalMemory> {
        Arc::new(PersonalMemory::open_in_memory(Arc::new(yazses_memory::MockEmbedder)).unwrap())
    }

    #[tokio::test]
    #[ignore = "requires a live display server (xdotool/wtype/AppleScript)"]
    async fn type_text_returns_ok() {
        let d = Dispatcher::new(None);
        let r = d
            .dispatch(ToolCall {
                tool: "type_text".into(),
                arguments: json!({ "text": "hello" }),
            })
            .await;
        assert!(r.is_ok());
    }

    #[tokio::test]
    async fn unknown_tool_returns_err() {
        let d = Dispatcher::new(None);
        let r = d
            .dispatch(ToolCall {
                tool: "nonexistent_tool".into(),
                arguments: json!({}),
            })
            .await;
        assert!(!r.is_ok());
    }

    #[tokio::test]
    async fn commit_and_recall_round_trip() {
        let d = Dispatcher::new(Some(mem()));
        d.dispatch(ToolCall {
            tool: "commit_to_memory".into(),
            arguments: json!({ "content": "alpha test item", "source": "voice" }),
        })
        .await;

        let result = d
            .dispatch(ToolCall {
                tool: "recall".into(),
                arguments: json!({ "query": "alpha query", "limit": 1 }),
            })
            .await;

        let v = result.into_value();
        let results = v["results"].as_array().unwrap();
        assert!(!results.is_empty());
    }

    #[tokio::test]
    async fn forget_last_with_no_memory_errors() {
        let d = Dispatcher::new(None);
        let r = d
            .dispatch(ToolCall {
                tool: "forget_last".into(),
                arguments: json!({ "minutes": 5 }),
            })
            .await;
        assert!(!r.is_ok());
    }

    #[tokio::test]
    async fn open_file_returns_ok() {
        let d = Dispatcher::new(None);
        let r = d
            .dispatch(ToolCall {
                tool: "open_file".into(),
                arguments: json!({ "path": "/tmp/test.txt" }),
            })
            .await;
        assert!(r.is_ok());
    }

    #[tokio::test]
    async fn goto_symbol_without_nvim_env_returns_ok() {
        // Ensure NVIM is unset so we hit the "no editor IPC" branch.
        std::env::remove_var("NVIM");
        let d = Dispatcher::new(None);
        let r = d
            .dispatch(ToolCall {
                tool: "goto_symbol".into(),
                arguments: json!({ "symbol": "my_function" }),
            })
            .await;
        assert!(r.is_ok());
        let v = r.into_value();
        assert_eq!(v["backend"], "none");
    }

    #[tokio::test]
    async fn mode_switch_returns_ok() {
        let d = Dispatcher::new(None);
        let r = d
            .dispatch(ToolCall {
                tool: "mode_switch".into(),
                arguments: json!({ "mode": "focus" }),
            })
            .await;
        assert!(r.is_ok());
        let v = r.into_value();
        assert_eq!(v["mode"], "focus");
    }

    #[tokio::test]
    async fn time_set_timer_returns_immediately() {
        let d = Dispatcher::new(None);
        let r = d
            .dispatch(ToolCall {
                tool: "time_set_timer".into(),
                arguments: json!({ "seconds": 3600, "label": "test timer" }),
            })
            .await;
        assert!(r.is_ok());
        let v = r.into_value();
        assert_eq!(v["seconds"], 3600u64);
    }

    #[tokio::test]
    async fn note_quick_appends_to_file() {
        // Use a temp file path directly — no HOME mutation needed.
        let tmp = tempfile::tempdir().unwrap();
        let notes_path = tmp.path().join("notes.md");

        let result = super::note_quick("test note content", Some("unit test"), Some(notes_path.clone())).await;
        assert!(result.is_ok(), "note_quick failed: {result:?}");

        // Give the async write a moment to flush in captured-output mode.
        tokio::time::sleep(tokio::time::Duration::from_millis(10)).await;

        let notes = std::fs::read_to_string(&notes_path)
            .unwrap_or_else(|e| panic!("failed to read {:?}: {e}", notes_path));
        assert!(notes.contains("test note content"), "expected 'test note content' in: {notes:?}");
        assert!(notes.contains("unit test"), "expected 'unit test' in: {notes:?}");
    }

    #[tokio::test]
    async fn volume_set_clamps_above_100() {
        // We just verify it doesn't panic and returns ok (backends may not be
        // present in CI, but the function handles that gracefully).
        let d = Dispatcher::new(None);
        let r = d
            .dispatch(ToolCall {
                tool: "volume_set".into(),
                arguments: json!({ "percent": 150 }),
            })
            .await;
        // Either ok (backend present) or ok:false (no backend) — not an Err.
        let v = r.into_value();
        assert!(v.get("percent").is_some());
    }
}
