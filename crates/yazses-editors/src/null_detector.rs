use crate::protocol::{WindowDetector, WindowInfo};

/// Graceful fallback when no compositor backend is available (adr-006 tier 5).
pub struct NullWindowDetector;

#[async_trait::async_trait]
impl WindowDetector for NullWindowDetector {
    fn name(&self) -> &str {
        "null"
    }

    async fn focused_window(&self) -> anyhow::Result<Option<WindowInfo>> {
        Ok(None)
    }
}
