use std::path::PathBuf;

use crate::protocol::{EditorBridge, EditorContext, WindowDetector, WindowInfo};

/// Deterministic window detector for unit tests.
pub struct MockWindowDetector {
    result: Option<WindowInfo>,
}

impl MockWindowDetector {
    pub fn focused(app_id: impl Into<String>, title: impl Into<String>) -> Self {
        Self {
            result: Some(WindowInfo {
                app_id: app_id.into(),
                title: title.into(),
                pid: None,
            }),
        }
    }

    pub fn none() -> Self {
        Self { result: None }
    }
}

#[async_trait::async_trait]
impl WindowDetector for MockWindowDetector {
    fn name(&self) -> &str {
        "mock"
    }

    async fn focused_window(&self) -> anyhow::Result<Option<WindowInfo>> {
        Ok(self.result.clone())
    }
}

/// Deterministic editor bridge for unit tests.
pub struct MockEditorBridge {
    context: Option<EditorContext>,
}

impl MockEditorBridge {
    pub fn with_context(ctx: EditorContext) -> Self {
        Self { context: Some(ctx) }
    }

    pub fn empty() -> Self {
        Self { context: None }
    }
}

#[async_trait::async_trait]
impl EditorBridge for MockEditorBridge {
    fn name(&self) -> &str {
        "mock"
    }

    async fn get_context(&self) -> anyhow::Result<Option<EditorContext>> {
        Ok(self.context.clone())
    }

    async fn get_active_file(&self) -> anyhow::Result<Option<PathBuf>> {
        Ok(self.context.as_ref().and_then(|c| c.file_path.clone()))
    }
}
