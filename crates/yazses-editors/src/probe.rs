use crate::null_detector::NullWindowDetector;
use crate::protocol::WindowDetector;

/// Probes for the best available compositor backend in priority order (adr-006):
///
/// 1. Hyprland IPC  (`hyprland` feature, checks `HYPRLAND_INSTANCE_SIGNATURE`)
/// 2. Sway IPC      (`sway` feature, checks `SWAYSOCK`)
/// 3. wlr-foreign-toplevel (`wlr-toplevel` feature, checks `WAYLAND_DISPLAY`)
/// 4. X11 EWMH      (`x11` feature, checks `DISPLAY`)
/// 5. `NullWindowDetector` — graceful fallback, always succeeds
///
/// Returns the first backend that can connect to the running compositor.
pub async fn probe_window_detector() -> Box<dyn WindowDetector> {
    // Tier 1 — Hyprland
    #[cfg(all(target_os = "linux", feature = "hyprland"))]
    if let Some(d) = crate::hyprland_detector::HyprlandWindowDetector::try_connect().await {
        tracing::info!("WindowDetector: using Hyprland IPC (tier 1)");
        return Box::new(d);
    }

    // Tier 2 — Sway
    #[cfg(all(target_os = "linux", feature = "sway"))]
    if let Some(d) = crate::sway_detector::SwayWindowDetector::try_connect().await {
        tracing::info!("WindowDetector: using Sway IPC (tier 2)");
        return Box::new(d);
    }

    // Tier 3 — wlr-foreign-toplevel
    #[cfg(all(target_os = "linux", feature = "wlr-toplevel"))]
    if let Some(d) = crate::wlr_detector::WlrForeignToplevelDetector::try_connect().await {
        tracing::info!("WindowDetector: using wlr-foreign-toplevel (tier 3)");
        return Box::new(d);
    }

    // Tier 4 — X11 EWMH
    #[cfg(all(target_os = "linux", feature = "x11"))]
    if let Some(d) = crate::x11_detector::X11EwhmWindowDetector::try_connect().await {
        tracing::info!("WindowDetector: using X11 EWMH (tier 4)");
        return Box::new(d);
    }

    // Tier 5 — Null fallback
    tracing::warn!("WindowDetector: no compositor backend available, using Null fallback");
    Box::new(NullWindowDetector)
}
