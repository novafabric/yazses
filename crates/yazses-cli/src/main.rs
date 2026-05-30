// YazSes v1.0 CLI — preserves every v0.4 subcommand and flag (adr-010).
//
// Phase 0: `status` fully implemented via IPC; all other subcommands are
// functional stubs that report their Phase readiness.  Each stub is replaced
// in the phase where the backing component is wired in:
//   start / stop     — Phase 0 (lifecycle via PID file + SIGTERM)
//   status           — Phase 0 (IPC `status` call)
//   doctor           — Phase 6 (port yazses.system.doctor to Rust)
//   inject           — Phase 1 (InjectorBackend wired)
//   remote           — Phase 4 (RemoteForwarder wired)
//   enroll           — Phase 6 (calibration wizard ported)
//   model            — Phase 3 (model pull/list/rm)
//   memory           — Phase 5 (PersonalMemory wired)
//   test             — Phase 1 (InjectorBackend wired)

use std::process::{self, Command, Stdio};

use anyhow::Context;
use clap::{Parser, Subcommand};
use serde_json::{Map, Value};

use yazses_core::{config, doctor, enroll};
use yazses_ipc::SyncIpcClient;

const VERSION: &str = env!("CARGO_PKG_VERSION");

#[derive(Parser)]
#[command(
    name = "yazses",
    about = "Local voice dictation daemon",
    version = VERSION
)]
struct Cli {
    #[command(subcommand)]
    command: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    /// Start the YazSes daemon in the background.
    Start,
    /// Stop the running daemon.
    Stop,
    /// Show daemon status.
    Status,
    /// Check system prerequisites.
    Doctor,
    /// Test text injection without recording.
    Inject {
        /// Text to inject into the focused application.
        text: String,
    },
    /// Forward voice typing to a remote host over SSH.
    Remote {
        host: String,
        #[arg(long, short, default_value_t = 22)]
        port: u16,
        #[arg(long, short = 'i', default_value = "")]
        key_file: String,
        #[arg(long)]
        stop: bool,
    },
    /// Run the accessibility enrollment wizard.
    Enroll,
    /// Manage LLM and ASR models.
    #[command(subcommand)]
    Model(ModelCmd),
    /// Manage the personal memory store.
    #[command(subcommand)]
    Memory(MemoryCmd),
    /// End-to-end self-test: types a test string into the focused window.
    Test,
    /// Package logs and config into a local tarball for debugging.
    ///
    /// Writes ~/yazses-bugreport-<timestamp>.tar.gz.
    /// Review it before sharing — it contains your config and recent logs.
    BugReport,
}

#[derive(Subcommand)]
enum ModelCmd {
    /// List available models and their download status.
    List,
    /// Download a model by name.
    Pull { name: String },
    /// Remove a downloaded model.
    Rm { name: String },
}

#[derive(Subcommand)]
enum MemoryCmd {
    /// Save text to the personal memory store.
    Commit {
        /// Text to remember.
        text: String,
        /// Optional source tag (default: "cli").
        #[arg(long, default_value = "cli")]
        source: String,
        /// Optional comma-separated tags.
        #[arg(long, default_value = "")]
        tags: String,
        /// Time-to-live in seconds (0 = never expire).
        #[arg(long, default_value_t = 0)]
        ttl: u64,
    },
    /// Search the personal memory store.
    Recall {
        /// Query string to search for.
        query: String,
        /// Maximum number of results to return.
        #[arg(long, short, default_value_t = 5)]
        limit: u64,
    },
    /// Delete the most recently committed memory entry.
    Forget,
    /// Show memory store status.
    Status,
    /// Permanently delete the personal-memory database.
    ///
    /// Requires `--i-mean-it` to prevent accidental data loss.
    Destroy {
        /// Confirm that you understand this action is irreversible.
        #[arg(long = "i-mean-it", required = true)]
        i_mean_it: bool,
    },
}

fn main() {
    let cli = Cli::parse();
    if let Err(e) = run(cli) {
        eprintln!("error: {e:#}");
        process::exit(1);
    }
}

fn run(cli: Cli) -> anyhow::Result<()> {
    match cli.command {
        Cmd::Start => cmd_start(),
        Cmd::Stop => cmd_stop(),
        Cmd::Status => cmd_status(),
        Cmd::Doctor => cmd_doctor(),
        Cmd::Inject { text } => cmd_inject(text),
        Cmd::Remote {
            host,
            port,
            key_file,
            stop,
        } => cmd_remote(host, port, key_file, stop),
        Cmd::Enroll => cmd_enroll(),
        Cmd::Model(m) => cmd_model(m),
        Cmd::Memory(m) => cmd_memory(m),
        Cmd::Test => cmd_test(),
        Cmd::BugReport => cmd_bugreport(),
    }
}

// ── start ──────────────────────────────────────────────────────────────────

fn cmd_start() -> anyhow::Result<()> {
    let pid_path = config::pid_path();
    if pid_path.exists() {
        if let Ok(pid_str) = std::fs::read_to_string(&pid_path) {
            if let Ok(pid) = pid_str.trim().parse::<u32>() {
                if process_is_running(pid) {
                    println!("YazSes is already running (PID {pid}).");
                    return Ok(());
                }
            }
        }
        std::fs::remove_file(&pid_path).ok();
    }

    let daemon_bin = std::env::current_exe()?
        .parent()
        .context("no parent dir")?
        .join("yazses-daemon");

    if !daemon_bin.exists() {
        anyhow::bail!(
            "daemon binary not found at {}; make sure yazses-daemon is on PATH",
            daemon_bin.display()
        );
    }

    Command::new(&daemon_bin)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .with_context(|| format!("spawning {}", daemon_bin.display()))?;

    println!("YazSes started. Hold Right Alt to dictate.");
    Ok(())
}

fn cmd_stop() -> anyhow::Result<()> {
    let pid_path = config::pid_path();
    if !pid_path.exists() {
        println!("YazSes is not running.");
        return Ok(());
    }
    let pid_str = std::fs::read_to_string(&pid_path)?;
    let pid: u32 = pid_str.trim().parse().context("invalid PID file")?;

    if !process_is_running(pid) {
        println!("YazSes is not running.");
        std::fs::remove_file(&pid_path).ok();
        return Ok(());
    }

    // Try graceful shutdown via IPC first.
    let socket_path = config::socket_path();
    if socket_path.exists() {
        if let Ok(client) = SyncIpcClient::new(&socket_path) {
            let _ = client.call("shutdown", Map::new());
            std::thread::sleep(std::time::Duration::from_millis(500));
            if !process_is_running(pid) {
                println!("YazSes stopped.");
                return Ok(());
            }
        }
    }

    // Fallback: SIGTERM
    #[cfg(unix)]
    unsafe {
        libc_kill(pid as i32, 15 /* SIGTERM */);
    }
    println!("YazSes stopped.");
    Ok(())
}

// ── status ─────────────────────────────────────────────────────────────────

fn cmd_status() -> anyhow::Result<()> {
    let socket_path = config::socket_path();

    let pid_path = config::pid_path();
    let pid: Option<u32> = pid_path
        .exists()
        .then(|| std::fs::read_to_string(&pid_path).ok())
        .flatten()
        .and_then(|s| s.trim().parse().ok());

    let is_running = pid.map(process_is_running).unwrap_or(false);
    if !is_running {
        println!("YazSes is not running.");
        return Ok(());
    }

    let client = SyncIpcClient::new(&socket_path).context("creating IPC client")?;

    match client.call("status", Map::new()) {
        Err(e) => {
            println!("YazSes is running (PID {pid:?}); IPC not yet ready: {e}");
        }
        Ok(info) => {
            let pid_str = pid.map(|p| p.to_string()).unwrap_or_else(|| "?".into());
            println!("YazSes is running (PID {pid_str}).");
            print_field("state", &info, "state");
            print_field("hotkey", &info, "hotkey");
            print_field("model", &info, "model");
            print_field("backend", &info, "injection_backend");
            print_field("uptime", &info, "uptime_s");
            if let Some(turns) = info.get("turn_count").and_then(Value::as_u64) {
                println!("  {:<10}{turns}", "turns");
            }
            if let Some(p50) = info.get("latency_p50_ms").and_then(Value::as_u64) {
                let p95 = info.get("latency_p95_ms").and_then(Value::as_u64).unwrap_or(0);
                println!("  {:<10}p50={p50}ms  p95={p95}ms", "latency");
            }
            if let Some(err) = info.get("last_error").and_then(Value::as_str) {
                if !err.is_empty() {
                    println!("  last err: {err}");
                }
            }
        }
    }
    Ok(())
}

fn print_field(label: &str, obj: &Value, key: &str) {
    if let Some(v) = obj.get(key) {
        let val = match v {
            Value::Null => "—".into(),
            Value::String(s) => s.clone(),
            other => other.to_string(),
        };
        println!("  {label:<10}{val}");
    }
}

// ── doctor ─────────────────────────────────────────────────────────────────

fn cmd_doctor() -> anyhow::Result<()> {
    let checks = doctor::run_checks();
    doctor::print_report(&checks);
    let failed = checks.iter().any(|c| c.status == doctor::CheckStatus::Fail);
    if failed {
        std::process::exit(1);
    }
    Ok(())
}

// ── inject ─────────────────────────────────────────────────────────────────

fn cmd_inject(text: String) -> anyhow::Result<()> {
    let socket_path = config::socket_path();
    if !socket_path.exists() {
        anyhow::bail!("daemon is not running; start it with: yazses start");
    }
    let client = SyncIpcClient::new(&socket_path)?;
    let mut params = Map::new();
    params.insert("text".into(), Value::String(text));
    let result = client.call("inject", params)?;
    println!("{result}");
    Ok(())
}

// ── remote ─────────────────────────────────────────────────────────────────

fn cmd_remote(host: String, port: u16, key_file: String, stop: bool) -> anyhow::Result<()> {
    let socket_path = config::socket_path();
    let client = SyncIpcClient::new(&socket_path)
        .context("daemon is not running; start it with: yazses start")?;

    if stop {
        let result = client.call("remote_stop", Map::new())?;
        println!("{result}");
    } else {
        let mut params = Map::new();
        params.insert("host".into(), Value::String(host));
        params.insert("port".into(), Value::Number(port.into()));
        params.insert("key_file".into(), Value::String(key_file));
        let result = client.call("remote_start", params)?;
        println!("{result}");
    }
    Ok(())
}

// ── enroll ─────────────────────────────────────────────────────────────────

fn cmd_enroll() -> anyhow::Result<()> {
    // Interactive wizard: wrap stdin-gated prompts around the recorder.
    struct InteractiveRecorder;

    impl enroll::AudioRecorder for InteractiveRecorder {
        fn record_seconds(&self, duration_s: f32) -> anyhow::Result<(Vec<f32>, u32)> {
            use anyhow::Context;
            use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
            use std::sync::{Arc, Mutex};

            let host = cpal::default_host();
            let device = host
                .default_input_device()
                .context("no default microphone")?;
            let config = device
                .default_input_config()
                .context("no default input config")?;
            let sample_rate = config.sample_rate();

            let buf: Arc<Mutex<Vec<f32>>> = Arc::new(Mutex::new(Vec::new()));
            let buf_clone = buf.clone();

            let stream = device
                .build_input_stream(
                    &config.into(),
                    move |data: &[f32], _| {
                        buf_clone.lock().unwrap().extend_from_slice(data);
                    },
                    |e| eprintln!("audio error: {e}"),
                    None,
                )
                .context("open microphone stream")?;

            stream.play().context("start stream")?;
            std::thread::sleep(std::time::Duration::from_secs_f32(duration_s));
            drop(stream);

            Ok((
                Arc::try_unwrap(buf).unwrap().into_inner().unwrap(),
                sample_rate,
            ))
        }
    }

    let result = enroll::run_wizard(&InteractiveRecorder, |msg| {
        // For prompts that ask "Press Enter", read stdin in the caller.
        if msg.contains("Press Enter") {
            print!("{msg} ");
            let _ = std::io::stdin().lines().next();
        } else {
            println!("{msg}");
        }
    })?;

    let config_path = config::config_file();
    enroll::write_config(&result, &config_path)?;
    println!("\nConfig written to {}", config_path.display());
    Ok(())
}

// ── model ──────────────────────────────────────────────────────────────────

struct ModelEntry {
    name: &'static str,
    description: &'static str,
    url: &'static str,
    filename: &'static str,
    size_mb: u64,
}

const MODELS: &[ModelEntry] = &[
    ModelEntry {
        name: "whisper-base",
        description: "Whisper base  — fast, English/multilingual, 145 MB",
        url: "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",
        filename: "ggml-base.bin",
        size_mb: 145,
    },
    ModelEntry {
        name: "whisper-small",
        description: "Whisper small — balanced speed/accuracy, 488 MB",
        url: "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin",
        filename: "ggml-small.bin",
        size_mb: 488,
    },
    ModelEntry {
        name: "whisper-large-v3-turbo",
        description: "Whisper large-v3-turbo — highest accuracy, 99 langs, 874 MB",
        url: "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin",
        filename: "ggml-large-v3-turbo.bin",
        size_mb: 874,
    },
];

fn model_cache_dir() -> std::path::PathBuf {
    let base = std::env::var_os("HF_HOME")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| {
            let home = std::env::var_os("HOME")
                .or_else(|| std::env::var_os("USERPROFILE"))
                .map(std::path::PathBuf::from)
                .unwrap_or_else(|| std::path::PathBuf::from("/tmp"));
            home.join(".cache").join("huggingface")
        });
    base.join("hub").join("whisper.cpp")
}

fn cmd_model(cmd: ModelCmd) -> anyhow::Result<()> {
    match cmd {
        ModelCmd::List => {
            let cache = model_cache_dir();
            println!("YazSes models (cached in {}):", cache.display());
            println!();
            for m in MODELS {
                let path = cache.join(m.filename);
                let status = if path.exists() { "✓ downloaded" } else { "  not cached" };
                println!("  {status}  {}  —  {}", m.name, m.description);
                if path.exists() {
                    println!("             path: {}", path.display());
                }
            }
            println!();
            println!("LLM models are served via Ollama (run `ollama list` to see available LLMs).");
        }

        ModelCmd::Pull { name } => {
            let entry = MODELS
                .iter()
                .find(|m| m.name == name)
                .ok_or_else(|| {
                    anyhow::anyhow!(
                        "unknown model '{}'; run `yazses model list` to see available models",
                        name
                    )
                })?;

            let cache = model_cache_dir();
            std::fs::create_dir_all(&cache)
                .with_context(|| format!("creating model cache dir {}", cache.display()))?;

            let dest = cache.join(entry.filename);
            if dest.exists() {
                println!("Already downloaded: {}", dest.display());
                return Ok(());
            }

            println!("Downloading {} (~{} MB)...", entry.name, entry.size_mb);
            println!("  from: {}", entry.url);
            println!("  to:   {}", dest.display());

            let tmp = dest.with_extension("bin.tmp");
            download_with_progress(entry.url, &tmp, entry.size_mb)
                .with_context(|| format!("downloading {}", entry.name))?;
            std::fs::rename(&tmp, &dest)
                .with_context(|| format!("moving {} to {}", tmp.display(), dest.display()))?;

            println!("\nDone. Model saved to {}", dest.display());
            println!("Start the daemon with: YAZSES_STT_MODEL={} yazses start", dest.display());
        }

        ModelCmd::Rm { name } => {
            let entry = MODELS
                .iter()
                .find(|m| m.name == name)
                .ok_or_else(|| anyhow::anyhow!("unknown model '{name}'"))?;

            let path = model_cache_dir().join(entry.filename);
            if !path.exists() {
                println!("Model '{name}' is not downloaded.");
                return Ok(());
            }
            std::fs::remove_file(&path)
                .with_context(|| format!("removing {}", path.display()))?;
            println!("Removed {}", path.display());
        }
    }
    Ok(())
}

fn download_with_progress(
    url: &str,
    dest: &std::path::Path,
    approx_mb: u64,
) -> anyhow::Result<()> {
    use std::io::{Read, Write};

    let mut resp = reqwest::blocking::get(url)
        .with_context(|| format!("GET {url}"))?
        .error_for_status()
        .with_context(|| format!("HTTP error for {url}"))?;

    let total = resp
        .headers()
        .get(reqwest::header::CONTENT_LENGTH)
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(approx_mb * 1024 * 1024);

    let mut file = std::fs::File::create(dest)
        .with_context(|| format!("creating {}", dest.display()))?;

    let mut downloaded: u64 = 0;
    let mut buf = vec![0u8; 256 * 1024];
    let mut last_pct = 0u64;

    loop {
        let n = resp.read(&mut buf).context("reading download stream")?;
        if n == 0 {
            break;
        }
        file.write_all(&buf[..n]).context("writing model file")?;
        downloaded += n as u64;
        let pct = downloaded * 100 / total.max(1);
        if pct >= last_pct + 5 {
            let mb = downloaded / (1024 * 1024);
            let total_mb = total / (1024 * 1024);
            print!("\r  {pct:3}%  {mb} / {total_mb} MB   ");
            std::io::stdout().flush().ok();
            last_pct = pct;
        }
    }

    Ok(())
}

// ── memory ─────────────────────────────────────────────────────────────────

fn cmd_memory(cmd: MemoryCmd) -> anyhow::Result<()> {
    // Destroy does not require the daemon to be running.
    if let MemoryCmd::Destroy { i_mean_it: _ } = &cmd {
        let db_path = config::memory_db_path();
        if db_path.exists() {
            std::fs::remove_file(&db_path)
                .with_context(|| format!("deleting {}", db_path.display()))?;
            println!("Memory database deleted: {}", db_path.display());
            println!("Your conversation history has been permanently erased.");
        } else {
            println!("No memory database found at {}.", db_path.display());
        }
        return Ok(());
    }

    let socket_path = config::socket_path();
    let client = SyncIpcClient::new(&socket_path)
        .context("daemon is not running — start it with: yazses start")?;

    match cmd {
        MemoryCmd::Commit {
            text,
            source,
            tags,
            ttl,
        } => {
            let mut params = Map::new();
            params.insert("content".into(), Value::String(text));
            params.insert("source".into(), Value::String(source));
            if !tags.is_empty() {
                let tag_list: Vec<Value> = tags
                    .split(',')
                    .map(|t| Value::String(t.trim().to_string()))
                    .collect();
                params.insert("tags".into(), Value::Array(tag_list));
            }
            params.insert("ttl_seconds".into(), Value::Number(ttl.into()));
            let result = client.call("memory_commit", params)?;
            if result.get("ok").and_then(Value::as_bool).unwrap_or(false) {
                let rowid = result.get("rowid").and_then(Value::as_i64).unwrap_or(-1);
                println!("Saved (rowid {rowid}).");
            } else {
                let reason = result
                    .get("reason")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown error");
                anyhow::bail!("memory commit failed: {reason}");
            }
        }

        MemoryCmd::Recall { query, limit } => {
            let mut params = Map::new();
            params.insert("query".into(), Value::String(query));
            params.insert("limit".into(), Value::Number(limit.into()));
            let result = client.call("memory_recall", params)?;
            if !result.get("ok").and_then(Value::as_bool).unwrap_or(false) {
                let reason = result
                    .get("reason")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown error");
                anyhow::bail!("memory recall failed: {reason}");
            }
            let items = result
                .get("results")
                .and_then(Value::as_array)
                .map(Vec::as_slice)
                .unwrap_or(&[]);
            if items.is_empty() {
                println!("No memories found.");
            } else {
                for (i, item) in items.iter().enumerate() {
                    let text = item.get("transcript").and_then(Value::as_str).unwrap_or("");
                    let source = item.get("source").and_then(Value::as_str).unwrap_or("");
                    let dist = item
                        .get("distance")
                        .and_then(Value::as_f64)
                        .map(|d| format!(" (dist {d:.3})"))
                        .unwrap_or_default();
                    println!("  [{i}] [{source}]{dist} {text}");
                }
            }
        }

        MemoryCmd::Forget => {
            let result = client.call("memory_forget", Map::new())?;
            if result.get("ok").and_then(Value::as_bool).unwrap_or(false) {
                println!("Last memory entry deleted.");
            } else {
                let reason = result
                    .get("reason")
                    .and_then(Value::as_str)
                    .unwrap_or("nothing to forget");
                println!("Nothing to forget: {reason}");
            }
        }

        MemoryCmd::Status => {
            let result = client.call("status", Map::new())?;
            let memory_active = result
                .get("memory_active")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            if memory_active {
                println!("Memory store: active (encrypted SQLite)");
            } else {
                println!("Memory store: active (plain SQLite, :memory: — restart daemon with encryption key to persist)");
            }
        }

        // Handled above before the IPC client is created; unreachable here.
        MemoryCmd::Destroy { .. } => unreachable!(),
    }
    Ok(())
}

// ── test ───────────────────────────────────────────────────────────────────

fn cmd_test() -> anyhow::Result<()> {
    println!("test: not yet implemented (Phase 1 — InjectorBackend).");
    println!("Run `uv run yazses test` to use the v0.4 Python implementation.");
    Ok(())
}

// ── bugreport ──────────────────────────────────────────────────────────────

fn cmd_bugreport() -> anyhow::Result<()> {
    use std::path::PathBuf;

    let timestamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();

    let report_name = format!("yazses-bugreport-{timestamp}");
    let report_dir = std::env::temp_dir().join(&report_name);
    std::fs::create_dir_all(&report_dir)?;

    // Collect log file
    let log_path = dirs::data_local_dir()
        .unwrap_or_else(|| PathBuf::from("~/.local/share"))
        .join("yazses/daemon.log");
    if log_path.exists() {
        let dest = report_dir.join("daemon.log");
        std::fs::copy(&log_path, dest)?;
    }

    // Collect config (no secrets — config contains no credentials)
    let config_dir = dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("~/.config"))
        .join("yazses");
    if config_dir.exists() {
        let dest = report_dir.join("config");
        copy_dir_safe(&config_dir, &dest)?;
    }

    // Write version / platform info
    let version_info = format!(
        "yazses {}\nos: {}\narch: {}\n",
        env!("CARGO_PKG_VERSION"),
        std::env::consts::OS,
        std::env::consts::ARCH,
    );
    std::fs::write(report_dir.join("version.txt"), version_info)?;

    // Create tarball using the system tar (available on Linux/macOS/WSL)
    let home = dirs::home_dir().unwrap_or_else(|| PathBuf::from("."));
    let tarball = home.join(format!("{report_name}.tar.gz"));
    let status = std::process::Command::new("tar")
        .arg("-czf")
        .arg(&tarball)
        .arg("-C")
        .arg(std::env::temp_dir())
        .arg(&report_name)
        .status()?;

    // Clean up temp staging dir
    let _ = std::fs::remove_dir_all(&report_dir);

    if status.success() {
        println!("Bug report written to: {}", tarball.display());
        println!("Review it before sharing — it may contain config details.");
    } else {
        println!("Warning: tar failed; staging dir left at: {}", report_dir.display());
    }
    Ok(())
}

fn copy_dir_safe(src: &std::path::Path, dst: &std::path::Path) -> anyhow::Result<()> {
    std::fs::create_dir_all(dst)?;
    for entry in std::fs::read_dir(src)? {
        let entry = entry?;
        let ftype = entry.file_type()?;
        let dst_path = dst.join(entry.file_name());
        if ftype.is_file() {
            std::fs::copy(entry.path(), dst_path)?;
        }
    }
    Ok(())
}

// ── helpers ────────────────────────────────────────────────────────────────

fn process_is_running(pid: u32) -> bool {
    #[cfg(unix)]
    {
        // kill(pid, 0) returns 0 if the process exists and we can signal it.
        unsafe { libc_kill(pid as i32, 0) == 0 }
    }
    #[cfg(windows)]
    {
        use std::os::windows::io::OwnedHandle;
        false // Phase 6 TODO
    }
}

#[cfg(unix)]
extern "C" {
    #[link_name = "kill"]
    fn libc_kill(pid: i32, sig: i32) -> i32;
}
