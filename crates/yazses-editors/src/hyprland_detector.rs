/// Hyprland IPC window detector — tier 1 of the four-tier WindowDetector (adr-006).
///
/// Requires: `HYPRLAND_INSTANCE_SIGNATURE` env var (set by Hyprland automatically).
/// **Feature gate:** `--features hyprland`
pub struct HyprlandWindowDetector;

impl HyprlandWindowDetector {
    /// Returns `Some(Self)` if `HYPRLAND_INSTANCE_SIGNATURE` is present in the environment,
    /// indicating the process is running inside a Hyprland session.
    #[cfg(all(target_os = "linux", feature = "hyprland"))]
    pub async fn try_connect() -> Option<Self> {
        if std::env::var("HYPRLAND_INSTANCE_SIGNATURE").is_ok() {
            Some(Self)
        } else {
            None
        }
    }
}

#[cfg(all(target_os = "linux", feature = "hyprland"))]
#[async_trait::async_trait]
impl crate::protocol::WindowDetector for HyprlandWindowDetector {
    fn name(&self) -> &str {
        "hyprland"
    }

    async fn focused_window(&self) -> anyhow::Result<Option<crate::protocol::WindowInfo>> {
        use hyprland::data::Client;
        use hyprland::shared::HyprDataActiveOptional;

        let client = tokio::task::spawn_blocking(|| Client::get_active())
            .await
            .map_err(|e| anyhow::anyhow!("Hyprland task join: {e}"))??;

        Ok(client.map(|c| crate::protocol::WindowInfo {
            app_id: c.class,
            title: c.title,
            pid: Some(c.pid as u32),
        }))
    }
}
