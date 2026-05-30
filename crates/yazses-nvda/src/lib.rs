// Windows NVDA screen-reader announcer.
//
// On Windows: attempts to load `nvdaControllerClient64.dll` (or 32-bit
// variant) and call `nvdaController_speakText`.  Falls back to Windows SAPI
// via `PowerShell -Command "Add-Type -AssemblyName System.Speech; ..."`.
//
// On non-Windows: `announce` is a silent no-op — use `yazses-atspi` on Linux
// or the macOS NSAccessibility path (Phase 7).

#[cfg(target_os = "windows")]
use tracing::debug;

/// Priority hint for the screen reader.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AnnouncePriority {
    Polite,
    Assertive,
}

/// Available announcement backend on this system.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Backend {
    Nvda,
    Sapi,
    None,
}

impl std::fmt::Display for Backend {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Nvda => write!(f, "NVDA controller DLL"),
            Self::Sapi => write!(f, "Windows SAPI (PowerShell)"),
            Self::None => write!(f, "none (silent)"),
        }
    }
}

/// Probe which backend is available without speaking anything.
pub fn probe() -> Backend {
    #[cfg(target_os = "windows")]
    {
        if nvda_dll_available() {
            return Backend::Nvda;
        }
        if sapi_available() {
            return Backend::Sapi;
        }
        Backend::None
    }
    #[cfg(not(target_os = "windows"))]
    {
        Backend::None
    }
}

/// Announce `text` to NVDA or SAPI (non-blocking, fire-and-forget).
/// On non-Windows platforms this is a no-op.
pub fn announce(text: &str, priority: AnnouncePriority) {
    let _ = try_announce(text, priority);
}

fn try_announce(text: &str, priority: AnnouncePriority) -> anyhow::Result<()> {
    #[cfg(target_os = "windows")]
    {
        announce_windows(text, priority)
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = (text, priority);
        Ok(())
    }
}

#[cfg(target_os = "windows")]
fn announce_windows(text: &str, _priority: AnnouncePriority) -> anyhow::Result<()> {
    // Try NVDA controller DLL first.
    if nvda_dll_available() {
        if let Ok(()) = speak_via_nvda(text) {
            return Ok(());
        }
    }

    // Fallback: Windows SAPI via PowerShell.
    speak_via_sapi(text)
}

/// Load nvdaControllerClient64.dll (or 32-bit) and call speakText.
///
/// The NVDA controller client DLL is distributed with NVDA and expected at
/// `%PROGRAMFILES%\NVDA\nvdaControllerClient64.dll` or on the PATH.
#[cfg(target_os = "windows")]
fn speak_via_nvda(text: &str) -> anyhow::Result<()> {
    use libloading::{Library, Symbol};

    let dll_path =
        locate_nvda_dll().ok_or_else(|| anyhow::anyhow!("nvdaControllerClient DLL not found"))?;

    // Safety: The NVDA controller DLL exports nvdaController_speakText with
    // the documented signature `error_status_t speakText(const wchar_t*)`.
    // We construct a null-terminated UTF-16 string and hold the Library alive
    // for the duration of the call.
    unsafe {
        let lib = Library::new(&dll_path)?;
        let speak: Symbol<unsafe extern "C" fn(*const u16) -> u32> =
            lib.get(b"nvdaController_speakText\0")?;

        let wide: Vec<u16> = text.encode_utf16().chain(std::iter::once(0)).collect();
        let ret = speak(wide.as_ptr());
        if ret != 0 {
            anyhow::bail!("nvdaController_speakText returned error code {ret}");
        }
    }
    debug!(backend = "nvda-dll", %text, "announced");
    Ok(())
}

#[cfg(target_os = "windows")]
fn speak_via_sapi(text: &str) -> anyhow::Result<()> {
    use std::process::Command;

    // Escape single quotes to avoid PowerShell injection.
    let safe_text = text.replace('\'', "''");
    let script = format!(
        "Add-Type -AssemblyName System.Speech; \
         $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; \
         $s.Speak('{safe_text}')"
    );

    Command::new("powershell")
        .args(["-NoProfile", "-NonInteractive", "-Command", &script])
        .spawn()?;

    debug!(backend = "sapi", %text, "announced");
    Ok(())
}

#[cfg(target_os = "windows")]
fn nvda_dll_available() -> bool {
    locate_nvda_dll().is_some()
}

#[cfg(target_os = "windows")]
fn locate_nvda_dll() -> Option<std::path::PathBuf> {
    use std::path::PathBuf;

    let candidates = [
        std::env::var("PROGRAMFILES").ok().map(|p| {
            PathBuf::from(p)
                .join("NVDA")
                .join("nvdaControllerClient64.dll")
        }),
        std::env::var("PROGRAMFILES(X86)").ok().map(|p| {
            PathBuf::from(p)
                .join("NVDA")
                .join("nvdaControllerClient32.dll")
        }),
        // Common portable install location
        Some(PathBuf::from("nvdaControllerClient64.dll")),
    ];

    candidates.into_iter().flatten().find(|p| p.exists())
}

#[cfg(target_os = "windows")]
fn sapi_available() -> bool {
    // PowerShell is always available on Windows; assume SAPI is too.
    true
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn probe_returns_backend_without_panic() {
        let b = probe();
        let s = b.to_string();
        assert!(!s.is_empty());
    }

    #[test]
    fn announce_does_not_panic() {
        announce("test announcement", AnnouncePriority::Polite);
    }

    #[test]
    fn backend_display() {
        assert_eq!(Backend::Nvda.to_string(), "NVDA controller DLL");
        assert_eq!(Backend::Sapi.to_string(), "Windows SAPI (PowerShell)");
        assert_eq!(Backend::None.to_string(), "none (silent)");
    }

    #[cfg(not(target_os = "windows"))]
    #[test]
    fn probe_returns_none_on_non_windows() {
        assert_eq!(probe(), Backend::None);
    }
}
