pub mod hyprland_detector;
pub mod mock;
pub mod neovim_bridge;
pub mod null_detector;
pub mod probe;
pub mod protocol;
pub mod sway_detector;
pub mod vscode_bridge;
pub mod wlr_detector;
pub mod x11_detector;

pub use mock::{MockEditorBridge, MockWindowDetector};
pub use neovim_bridge::NeovimBridge;
pub use null_detector::NullWindowDetector;
pub use probe::probe_window_detector;
pub use protocol::{
    CursorContext, Edit, EditorBridge, EditorContext, Import, Symbol, WindowDetector, WindowInfo,
};
pub use vscode_bridge::VSCodeBridge;

#[cfg(all(target_os = "linux", feature = "hyprland"))]
pub use hyprland_detector::HyprlandWindowDetector;

#[cfg(all(target_os = "linux", feature = "sway"))]
pub use sway_detector::SwayWindowDetector;

#[cfg(all(target_os = "linux", feature = "wlr-toplevel"))]
pub use wlr_detector::WlrForeignToplevelDetector;

#[cfg(all(target_os = "linux", feature = "x11"))]
pub use x11_detector::X11EwhmWindowDetector;

// ── Unit tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    // ── EditorContext helpers ─────────────────────────────────────────────────

    #[test]
    fn initial_prompt_empty_symbols() {
        let ctx = EditorContext::default();
        assert_eq!(ctx.to_initial_prompt(224), "");
    }

    #[test]
    fn initial_prompt_joins_symbols() {
        let ctx = EditorContext {
            recent_symbols: vec![
                Symbol {
                    name: "foo".into(),
                    kind: "function".into(),
                    file: None,
                },
                Symbol {
                    name: "bar".into(),
                    kind: "class".into(),
                    file: None,
                },
            ],
            ..Default::default()
        };
        assert_eq!(ctx.to_initial_prompt(224), "foo, bar");
    }

    #[test]
    fn initial_prompt_truncates_at_budget() {
        // budget of 1 BPE token ≈ 4 chars; "foo" fits, ", barbaz" would exceed
        let ctx = EditorContext {
            recent_symbols: vec![
                Symbol {
                    name: "foo".into(),
                    kind: "fn".into(),
                    file: None,
                },
                Symbol {
                    name: "barbaz".into(),
                    kind: "fn".into(),
                    file: None,
                },
            ],
            ..Default::default()
        };
        let prompt = ctx.to_initial_prompt(1); // 4 char budget
        assert_eq!(prompt, "foo");
    }

    #[test]
    fn llm_block_empty_context() {
        let ctx = EditorContext::default();
        let block = ctx.to_llm_block();
        assert!(block.starts_with("<editor_context>"));
        assert!(block.ends_with("</editor_context>"));
    }

    #[test]
    fn llm_block_contains_file_and_symbols() {
        use std::path::PathBuf;
        let ctx = EditorContext {
            file_path: Some(PathBuf::from("/src/main.rs")),
            language: Some("rust".into()),
            recent_symbols: vec![Symbol {
                name: "my_fn".into(),
                kind: "function".into(),
                file: None,
            }],
            ..Default::default()
        };
        let block = ctx.to_llm_block();
        assert!(block.contains("file: /src/main.rs"));
        assert!(block.contains("language: rust"));
        assert!(block.contains("symbols: my_fn"));
    }

    // ── WindowInfo ────────────────────────────────────────────────────────────

    #[test]
    fn window_info_nvim_is_editor() {
        let w = WindowInfo {
            app_id: "nvim".into(),
            title: "main.rs".into(),
            pid: None,
        };
        assert!(w.is_editor());
    }

    #[test]
    fn window_info_browser_is_not_editor() {
        let w = WindowInfo {
            app_id: "firefox".into(),
            title: "GitHub".into(),
            pid: None,
        };
        assert!(!w.is_editor());
    }

    // ── NullWindowDetector ────────────────────────────────────────────────────

    #[tokio::test]
    async fn null_detector_returns_none() {
        let d = NullWindowDetector;
        let result = d.focused_window().await.unwrap();
        assert!(result.is_none());
    }

    // ── MockEditorBridge ──────────────────────────────────────────────────────

    #[tokio::test]
    async fn mock_bridge_empty_returns_none() {
        let bridge = MockEditorBridge::empty();
        assert!(bridge.get_context().await.unwrap().is_none());
    }

    #[tokio::test]
    async fn mock_bridge_with_context_returns_it() {
        use std::path::PathBuf;
        let ctx = EditorContext {
            file_path: Some(PathBuf::from("/foo.rs")),
            language: Some("rust".into()),
            ..Default::default()
        };
        let bridge = MockEditorBridge::with_context(ctx.clone());
        let got = bridge.get_context().await.unwrap().unwrap();
        assert_eq!(got.file_path, Some(PathBuf::from("/foo.rs")));
        assert_eq!(got.language.as_deref(), Some("rust"));
    }
}
