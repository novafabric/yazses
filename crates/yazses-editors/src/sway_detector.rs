/// Sway/i3 IPC window detector — tier 2 of the four-tier WindowDetector (adr-006).
///
/// Works on Sway and any i3-compatible compositor.
/// Checks for `SWAYSOCK` environment variable before attempting connection.
/// **Feature gate:** `--features sway`
pub struct SwayWindowDetector;

impl SwayWindowDetector {
    #[cfg(all(target_os = "linux", feature = "sway"))]
    pub async fn try_connect() -> Option<Self> {
        if std::env::var("SWAYSOCK").is_ok() {
            Some(Self)
        } else {
            None
        }
    }
}

#[cfg(all(target_os = "linux", feature = "sway"))]
#[async_trait::async_trait]
impl crate::protocol::WindowDetector for SwayWindowDetector {
    fn name(&self) -> &str {
        "sway"
    }

    async fn focused_window(&self) -> anyhow::Result<Option<crate::protocol::WindowInfo>> {
        let result = tokio::task::spawn_blocking(
            || -> anyhow::Result<Option<crate::protocol::WindowInfo>> {
                let mut conn = swayipc::Connection::new()?;
                let tree = conn.get_tree()?;
                Ok(find_focused(&tree).map(|node| crate::protocol::WindowInfo {
                    app_id: node
                        .app_id
                        .clone()
                        .or_else(|| {
                            node.window_properties
                                .as_ref()
                                .and_then(|p| p.class.clone())
                        })
                        .unwrap_or_default(),
                    title: node.name.clone().unwrap_or_default(),
                    pid: node.pid.map(|p| p as u32),
                }))
            },
        )
        .await
        .map_err(|e| anyhow::anyhow!("Sway task join: {e}"))??;

        Ok(result)
    }
}

#[cfg(all(target_os = "linux", feature = "sway"))]
fn find_focused(node: &swayipc::Node) -> Option<&swayipc::Node> {
    if node.focused {
        return Some(node);
    }
    for child in node.nodes.iter().chain(node.floating_nodes.iter()) {
        if let Some(found) = find_focused(child) {
            return Some(found);
        }
    }
    None
}
