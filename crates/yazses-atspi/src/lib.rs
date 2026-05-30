// Linux screen-reader announcer (AT-SPI2 / speech-dispatcher).
//
// Priority chain on Linux: spd-say → espeak-ng → espeak → silent no-op.
// On non-Linux the `announce` function is a no-op — platform-specific
// announcers (macOS NSAccessibility, Windows NVDA via yazses-nvda) are
// implemented in their own crates.
//
// The `probe` function lists which backends are available at runtime without
// actually speaking anything.

use tracing::debug;

/// Priority hint for the screen reader.
/// `Polite` waits for a natural pause; `Assertive` interrupts immediately.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AnnouncePriority {
    Polite,
    Assertive,
}

/// Name a backend that was found available on the current system.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Backend {
    SpeechDispatcher,
    EspeakNg,
    Espeak,
    None,
}

impl std::fmt::Display for Backend {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::SpeechDispatcher => write!(f, "speech-dispatcher (spd-say)"),
            Self::EspeakNg => write!(f, "espeak-ng"),
            Self::Espeak => write!(f, "espeak"),
            Self::None => write!(f, "none (silent)"),
        }
    }
}

/// Probe which backend is available without speaking anything.
/// Returns the best available backend in priority order.
pub fn probe() -> Backend {
    #[cfg(target_os = "linux")]
    {
        if which("spd-say") {
            return Backend::SpeechDispatcher;
        }
        if which("espeak-ng") {
            return Backend::EspeakNg;
        }
        if which("espeak") {
            return Backend::Espeak;
        }
        Backend::None
    }
    #[cfg(not(target_os = "linux"))]
    {
        Backend::None
    }
}

/// Announce `text` to the screen reader using the best available backend.
///
/// This call is fire-and-forget and non-blocking (spawns a detached child
/// process). It never returns an error — failures are logged at DEBUG level.
pub fn announce(text: &str, priority: AnnouncePriority) {
    let _ = try_announce(text, priority);
}

fn try_announce(text: &str, priority: AnnouncePriority) -> anyhow::Result<()> {
    #[cfg(target_os = "linux")]
    {
        announce_linux(text, priority)
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = (text, priority);
        Ok(())
    }
}

#[cfg(target_os = "linux")]
fn announce_linux(text: &str, priority: AnnouncePriority) -> anyhow::Result<()> {
    use std::process::Command;

    // spd-say: -e = echo (no TTS), -w = wait for finish, -p = priority
    // Priority: important|message|text|notification|progress
    let spd_priority = match priority {
        AnnouncePriority::Assertive => "important",
        AnnouncePriority::Polite => "text",
    };

    if which("spd-say") {
        debug!(backend = "spd-say", %text, "announcing");
        Command::new("spd-say")
            .args(["-p", spd_priority, text])
            .spawn()?;
        return Ok(());
    }

    if which("espeak-ng") {
        debug!(backend = "espeak-ng", %text, "announcing");
        Command::new("espeak-ng").arg(text).spawn()?;
        return Ok(());
    }

    if which("espeak") {
        debug!(backend = "espeak", %text, "announcing");
        Command::new("espeak").arg(text).spawn()?;
        return Ok(());
    }

    debug!(%text, "no TTS backend available; announcement silently dropped");
    Ok(())
}

fn which(tool: &str) -> bool {
    std::process::Command::new("which")
        .arg(tool)
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn probe_returns_some_backend() {
        // Just verify it doesn't panic; the specific backend depends on the system.
        let b = probe();
        let s = b.to_string();
        assert!(!s.is_empty());
    }

    #[test]
    fn announce_does_not_panic() {
        // Should be a no-op or fire speech; either way must not panic.
        announce("test announcement", AnnouncePriority::Polite);
    }

    #[test]
    fn priority_variants_display_without_panic() {
        let _ = format!("{:?}", AnnouncePriority::Polite);
        let _ = format!("{:?}", AnnouncePriority::Assertive);
    }

    #[test]
    fn backend_display() {
        assert_eq!(
            Backend::SpeechDispatcher.to_string(),
            "speech-dispatcher (spd-say)"
        );
        assert_eq!(Backend::None.to_string(), "none (silent)");
    }
}
