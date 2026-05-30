use std::path::{Path, PathBuf};

/// Resolve the platform-appropriate runtime directory for IPC sockets and PID file.
///
/// Linux/macOS: `$XDG_RUNTIME_DIR/yazses/` (falls back to `/tmp/yazses-$UID/`).
/// Windows: `%LOCALAPPDATA%\yazses\run\` (Phase 6; stubbed for now).
pub fn runtime_dir() -> PathBuf {
    #[cfg(unix)]
    {
        if let Some(xdg) = std::env::var_os("XDG_RUNTIME_DIR") {
            return PathBuf::from(xdg).join("yazses");
        }
        let uid = libc_getuid();
        PathBuf::from(format!("/tmp/yazses-{uid}"))
    }
    #[cfg(windows)]
    {
        let appdata = std::env::var("LOCALAPPDATA").unwrap_or_else(|_| "C:\\Temp".into());
        PathBuf::from(appdata).join("yazses").join("run")
    }
}

pub fn socket_path() -> PathBuf {
    runtime_dir().join("daemon.sock")
}

pub fn pid_path() -> PathBuf {
    runtime_dir().join("daemon.pid")
}

/// Platform-appropriate user config directory.
/// Linux/macOS: `~/.config/yazses/`  Windows: `%APPDATA%\yazses\`
pub fn config_dir() -> PathBuf {
    #[cfg(unix)]
    {
        let xdg = std::env::var_os("XDG_CONFIG_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| home_dir().join(".config"));
        xdg.join("yazses")
    }
    #[cfg(windows)]
    {
        let appdata = std::env::var("APPDATA")
            .unwrap_or_else(|_| "C:\\Users\\Default\\AppData\\Roaming".into());
        PathBuf::from(appdata).join("yazses")
    }
}

/// Path to `config.toml` inside the config directory.
pub fn config_file() -> PathBuf {
    config_dir().join("config.toml")
}

/// Platform-appropriate user data directory.
/// Linux: `~/.local/share/yazses/`  macOS: `~/Library/Application Support/yazses/`  Windows: `%LOCALAPPDATA%\yazses\`
pub fn data_dir() -> PathBuf {
    #[cfg(target_os = "linux")]
    {
        let xdg = std::env::var_os("XDG_DATA_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| home_dir().join(".local").join("share"));
        xdg.join("yazses")
    }
    #[cfg(target_os = "macos")]
    {
        home_dir()
            .join("Library")
            .join("Application Support")
            .join("yazses")
    }
    #[cfg(windows)]
    {
        let localappdata = std::env::var("LOCALAPPDATA")
            .unwrap_or_else(|_| "C:\\Users\\Default\\AppData\\Local".into());
        PathBuf::from(localappdata).join("yazses")
    }
    #[cfg(not(any(target_os = "linux", target_os = "macos", windows)))]
    {
        home_dir().join(".yazses")
    }
}

pub fn memory_db_path() -> PathBuf {
    data_dir().join("memory.db")
}

pub fn salt_path() -> PathBuf {
    data_dir().join(".salt")
}

fn home_dir() -> PathBuf {
    std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/tmp"))
}

// Suppress unused import on non-unix platforms
#[allow(dead_code)]
fn _use_path_type(_: &Path) {}

#[cfg(unix)]
fn libc_getuid() -> u32 {
    extern "C" {
        fn getuid() -> u32;
    }
    // Safety: getuid(2) has no preconditions; always safe to call.
    unsafe { getuid() }
}
