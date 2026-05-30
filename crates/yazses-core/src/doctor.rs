// YazSes doctor — system prerequisite checks (FR-22).
//
// Returns structured `DoctorCheck` results so the CLI can format them and
// tests can assert on status without parsing printed output.

use std::path::PathBuf;

/// Result of a single prerequisite check.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CheckStatus {
    Ok,
    Warn,
    Fail,
    Skip,
}

impl CheckStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Ok => "OK",
            Self::Warn => "WARN",
            Self::Fail => "FAIL",
            Self::Skip => "SKIP",
        }
    }
}

#[derive(Debug, Clone)]
pub struct DoctorCheck {
    pub name: String,
    pub status: CheckStatus,
    pub detail: String,
}

impl DoctorCheck {
    fn ok(name: impl Into<String>, detail: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            status: CheckStatus::Ok,
            detail: detail.into(),
        }
    }
    fn warn(name: impl Into<String>, detail: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            status: CheckStatus::Warn,
            detail: detail.into(),
        }
    }
    fn fail(name: impl Into<String>, detail: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            status: CheckStatus::Fail,
            detail: detail.into(),
        }
    }
    fn skip(name: impl Into<String>, detail: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            status: CheckStatus::Skip,
            detail: detail.into(),
        }
    }
}

/// Run all prerequisite checks and return results.
pub fn run_checks() -> Vec<DoctorCheck> {
    let mut out = Vec::new();
    out.push(DoctorCheck::ok("Platform", std::env::consts::OS));
    out.extend(check_keyboard_capture());
    out.extend(check_microphone());
    out.extend(check_session_type());
    out.extend(check_injection_tools());
    out.extend(check_model_cache());
    out.extend(check_config_dir());
    out.extend(check_accessibility_tools());
    out.extend(check_talon_coexistence());
    out
}

/// Print a human-readable report to stdout.
pub fn print_report(checks: &[DoctorCheck]) {
    let platform = std::env::consts::OS;
    println!("YazSes doctor ({platform}):");
    for c in checks {
        println!("  [{}] {}: {}", c.status.as_str(), c.name, c.detail);
    }
    println!();
    let fails = checks
        .iter()
        .filter(|c| c.status == CheckStatus::Fail)
        .count();
    let warns = checks
        .iter()
        .filter(|c| c.status == CheckStatus::Warn)
        .count();
    if fails > 0 {
        println!("  {fails} check(s) failed — fix the issues above then re-run `yazses doctor`.");
    } else if warns > 0 {
        println!("  {warns} warning(s) — YazSes should work but some features may be degraded.");
    } else {
        println!("  All checks passed.");
    }
}

// ── Individual checks ─────────────────────────────────────────────────────────

fn check_keyboard_capture() -> Vec<DoctorCheck> {
    #[cfg(target_os = "linux")]
    {
        let in_input_group = std::process::Command::new("id")
            .arg("-Gn")
            .output()
            .ok()
            .and_then(|o| String::from_utf8(o.stdout).ok())
            .map(|s| s.split_whitespace().any(|g| g == "input"))
            .unwrap_or(false);

        if in_input_group {
            return vec![DoctorCheck::ok(
                "Keyboard capture",
                "user is in the `input` group",
            )];
        }

        // Check if at least one event device is readable.
        let can_read = std::fs::read_dir("/dev/input")
            .map(|dir| {
                dir.filter_map(|e| e.ok()).any(|e| {
                    let p = e.path();
                    p.file_name()
                        .and_then(|n| n.to_str())
                        .map(|n| n.starts_with("event"))
                        .unwrap_or(false)
                        && std::fs::OpenOptions::new().read(true).open(&p).is_ok()
                })
            })
            .unwrap_or(false);

        if can_read {
            vec![DoctorCheck::warn(
                "Keyboard capture",
                "not in `input` group but devices are readable; \
                 add with: sudo usermod -aG input $USER && log out",
            )]
        } else {
            vec![DoctorCheck::fail(
                "Keyboard capture",
                "no access to /dev/input/event* — run: sudo usermod -aG input $USER && log out",
            )]
        }
    }
    #[cfg(target_os = "macos")]
    {
        vec![DoctorCheck::warn(
            "Keyboard capture",
            "grant Accessibility in System Settings → Privacy & Security → Accessibility",
        )]
    }
    #[cfg(target_os = "windows")]
    {
        vec![DoctorCheck::ok(
            "Keyboard capture",
            "Win32 RawInput — no special permissions required",
        )]
    }
    #[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "windows")))]
    {
        vec![DoctorCheck::skip(
            "Keyboard capture",
            "unsupported platform",
        )]
    }
}

fn check_microphone() -> Vec<DoctorCheck> {
    #[cfg(target_os = "linux")]
    {
        match std::fs::read_to_string("/proc/asound/cards") {
            Ok(s) if !s.trim().is_empty() && !s.contains("no soundcards") => {
                vec![DoctorCheck::ok("Microphone", "ALSA sound cards found")]
            }
            _ => vec![DoctorCheck::warn(
                "Microphone",
                "no ALSA sound cards detected — check your audio setup",
            )],
        }
    }
    #[cfg(not(target_os = "linux"))]
    {
        vec![DoctorCheck::ok("Microphone", "platform audio available")]
    }
}

fn check_session_type() -> Vec<DoctorCheck> {
    #[cfg(target_os = "linux")]
    {
        let is_wayland = std::env::var("WAYLAND_DISPLAY").is_ok();
        let is_x11 = std::env::var("DISPLAY").is_ok();
        let session = if is_wayland {
            "Wayland"
        } else if is_x11 {
            "X11"
        } else {
            "unknown"
        };
        let status = if is_wayland || is_x11 {
            CheckStatus::Ok
        } else {
            CheckStatus::Warn
        };
        vec![DoctorCheck {
            name: "Session type".into(),
            status,
            detail: session.into(),
        }]
    }
    #[cfg(not(target_os = "linux"))]
    {
        vec![]
    }
}

fn check_injection_tools() -> Vec<DoctorCheck> {
    #[cfg(target_os = "linux")]
    {
        let is_wayland = std::env::var("WAYLAND_DISPLAY").is_ok();
        let is_x11 = std::env::var("DISPLAY").is_ok();

        let tools: &[(&str, bool)] = &[
            ("xdotool", is_x11 || !is_wayland),
            ("ydotool", is_wayland),
            ("wtype", is_wayland),
            ("xclip", is_x11 || !is_wayland),
            ("wl-copy", is_wayland),
        ];

        tools
            .iter()
            .map(|(name, required)| {
                if which(name) {
                    DoctorCheck::ok(format!("  {name}"), "found")
                } else if *required {
                    DoctorCheck::fail(
                        format!("  {name}"),
                        "not installed — install with your package manager",
                    )
                } else {
                    DoctorCheck::skip(format!("  {name}"), "not needed on this session type")
                }
            })
            .collect()
    }
    #[cfg(not(target_os = "linux"))]
    {
        vec![]
    }
}

fn check_model_cache() -> Vec<DoctorCheck> {
    let hub = hf_hub_dir();
    if hub.exists() {
        vec![DoctorCheck::ok("Model cache", hub.display().to_string())]
    } else {
        vec![DoctorCheck::warn(
            "Model cache",
            format!(
                "{} (not found — run `yazses model pull` to download models)",
                hub.display()
            ),
        )]
    }
}

fn check_config_dir() -> Vec<DoctorCheck> {
    let dir = crate::config::config_dir();
    if dir.exists() {
        vec![DoctorCheck::ok("Config dir", dir.display().to_string())]
    } else {
        match std::fs::create_dir_all(&dir) {
            Ok(_) => vec![DoctorCheck::ok(
                "Config dir",
                format!("{} (created)", dir.display()),
            )],
            Err(e) => vec![DoctorCheck::fail(
                "Config dir",
                format!("could not create {}: {e}", dir.display()),
            )],
        }
    }
}

fn check_accessibility_tools() -> Vec<DoctorCheck> {
    #[cfg(target_os = "linux")]
    {
        if which("spd-say") {
            vec![DoctorCheck::ok(
                "Screen reader",
                "speech-dispatcher (spd-say) found",
            )]
        } else if which("espeak-ng") || which("espeak") {
            vec![DoctorCheck::warn(
                "Screen reader",
                "speech-dispatcher not found; espeak fallback available",
            )]
        } else {
            vec![DoctorCheck::warn(
                "Screen reader",
                "no TTS tool found (install speech-dispatcher or espeak-ng) — \
                 screen reader announcements will be silent",
            )]
        }
    }
    #[cfg(target_os = "macos")]
    {
        vec![DoctorCheck::ok(
            "Screen reader",
            "macOS VoiceOver via NSAccessibility (built-in)",
        )]
    }
    #[cfg(target_os = "windows")]
    {
        vec![DoctorCheck::ok(
            "Screen reader",
            "NVDA/SAPI support available",
        )]
    }
    #[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "windows")))]
    {
        vec![]
    }
}

fn check_talon_coexistence() -> Vec<DoctorCheck> {
    let talon_dir = home_dir().join(".talon");
    if !talon_dir.exists() {
        return vec![DoctorCheck::skip("Talon coexistence", "Talon not detected")];
    }

    let coexist_path = talon_dir.join("user").join("yazses_coexist.talon");
    if coexist_path.exists() {
        return vec![DoctorCheck::ok(
            "Talon coexistence",
            coexist_path.display().to_string(),
        )];
    }

    match write_talon_coexist_config(&coexist_path) {
        Ok(_) => vec![DoctorCheck::ok(
            "Talon coexistence",
            format!("{} (created)", coexist_path.display()),
        )],
        Err(e) => vec![DoctorCheck::warn(
            "Talon coexistence",
            format!("could not create coexist config: {e}"),
        )],
    }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

fn write_talon_coexist_config(path: &std::path::Path) -> anyhow::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(path, TALON_COEXIST)?;
    Ok(())
}

/// Talon config that suppresses Talon voice commands while YazSes is recording.
/// YazSes sets/clears the `user.yazses_recording` tag via IPC at hold-key events.
const TALON_COEXIST: &str = "\
# YazSes coexistence — auto-generated by `yazses doctor`
# Disables Talon commands while YazSes hold-key is active.
tag: user.yazses_recording
-
";

fn which(tool: &str) -> bool {
    #[cfg(unix)]
    return std::process::Command::new("which")
        .arg(tool)
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false);

    #[cfg(windows)]
    return std::process::Command::new("where.exe")
        .arg(tool)
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false);

    #[cfg(not(any(unix, windows)))]
    return false;
}

fn home_dir() -> PathBuf {
    std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/tmp"))
}

fn hf_hub_dir() -> PathBuf {
    std::env::var_os("HF_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| home_dir().join(".cache").join("huggingface"))
        .join("hub")
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn run_checks_returns_at_least_platform() {
        let checks = run_checks();
        assert!(!checks.is_empty());
        assert_eq!(checks[0].name, "Platform");
        assert_eq!(checks[0].status, CheckStatus::Ok);
    }

    #[test]
    fn check_status_strings() {
        assert_eq!(CheckStatus::Ok.as_str(), "OK");
        assert_eq!(CheckStatus::Warn.as_str(), "WARN");
        assert_eq!(CheckStatus::Fail.as_str(), "FAIL");
        assert_eq!(CheckStatus::Skip.as_str(), "SKIP");
    }

    #[test]
    fn config_dir_check_creates_or_finds_dir() {
        let checks = check_config_dir();
        assert!(!checks.is_empty());
        // Should be Ok whether dir pre-existed or was just created.
        assert_eq!(checks[0].status, CheckStatus::Ok);
    }

    #[test]
    fn model_cache_check_returns_some_status() {
        let checks = check_model_cache();
        assert_eq!(checks.len(), 1);
        // May be Ok or Warn depending on whether HF cache exists.
        assert!(matches!(
            checks[0].status,
            CheckStatus::Ok | CheckStatus::Warn
        ));
    }

    #[test]
    fn talon_check_returns_skip_when_not_installed() {
        // Without mocking HOME, we can only verify it runs without panic.
        let checks = check_talon_coexistence();
        assert!(!checks.is_empty());
    }
}
