/// wlr-foreign-toplevel window detector — tier 3 of the four-tier WindowDetector (adr-006).
///
/// Covers: River, Wayfire, labwc, COSMIC, and any compositor implementing the
/// `zwlr_foreign_toplevel_manager_v1` Wayland protocol extension.
/// **Feature gate:** `--features wlr-toplevel`
pub struct WlrForeignToplevelDetector;

impl WlrForeignToplevelDetector {
    #[cfg(all(target_os = "linux", feature = "wlr-toplevel"))]
    pub async fn try_connect() -> Option<Self> {
        if std::env::var("WAYLAND_DISPLAY").is_ok() {
            Some(Self)
        } else {
            None
        }
    }
}

#[cfg(all(target_os = "linux", feature = "wlr-toplevel"))]
#[async_trait::async_trait]
impl crate::protocol::WindowDetector for WlrForeignToplevelDetector {
    fn name(&self) -> &str {
        "wlr-foreign-toplevel"
    }

    async fn focused_window(&self) -> anyhow::Result<Option<crate::protocol::WindowInfo>> {
        tokio::task::spawn_blocking(query_focused_wlr)
            .await
            .map_err(|e| anyhow::anyhow!("wlr task join: {e}"))?
    }
}

// ── Wayland blocking implementation ──────────────────────────────────────────

#[cfg(all(target_os = "linux", feature = "wlr-toplevel"))]
fn query_focused_wlr() -> anyhow::Result<Option<crate::protocol::WindowInfo>> {
    use wayland_client::protocol::wl_registry::{self, WlRegistry};
    use wayland_client::{Connection, Dispatch, QueueHandle};
    use wayland_protocols_wlr::foreign_toplevel::v1::client::{
        zwlr_foreign_toplevel_handle_v1::{self, ZwlrForeignToplevelHandleV1},
        zwlr_foreign_toplevel_manager_v1::{self, ZwlrForeignToplevelManagerV1},
    };

    #[derive(Default)]
    struct ToplevelInfo {
        app_id: Option<String>,
        title: Option<String>,
        activated: bool,
    }

    #[derive(Default)]
    struct WlrState {
        manager: Option<ZwlrForeignToplevelManagerV1>,
        // Each entry: (handle, per-handle info). Handles are compared by identity.
        toplevels: Vec<(ZwlrForeignToplevelHandleV1, ToplevelInfo)>,
    }

    impl Dispatch<WlRegistry, ()> for WlrState {
        fn event(
            state: &mut Self,
            registry: &WlRegistry,
            event: wl_registry::Event,
            _: &(),
            _: &Connection,
            qh: &QueueHandle<Self>,
        ) {
            if let wl_registry::Event::Global {
                name,
                interface,
                version,
            } = event
            {
                if interface == "zwlr_foreign_toplevel_manager_v1" {
                    state.manager = Some(registry.bind::<ZwlrForeignToplevelManagerV1, _, _>(
                        name,
                        version.min(3),
                        qh,
                        (),
                    ));
                }
            }
        }
    }

    impl Dispatch<ZwlrForeignToplevelManagerV1, ()> for WlrState {
        fn event(
            state: &mut Self,
            _: &ZwlrForeignToplevelManagerV1,
            event: zwlr_foreign_toplevel_manager_v1::Event,
            _: &(),
            _: &Connection,
            _: &QueueHandle<Self>,
        ) {
            if let zwlr_foreign_toplevel_manager_v1::Event::Toplevel { toplevel } = event {
                state.toplevels.push((toplevel, ToplevelInfo::default()));
            }
        }
    }

    impl Dispatch<ZwlrForeignToplevelHandleV1, ()> for WlrState {
        fn event(
            state: &mut Self,
            proxy: &ZwlrForeignToplevelHandleV1,
            event: zwlr_foreign_toplevel_handle_v1::Event,
            _: &(),
            _: &Connection,
            _: &QueueHandle<Self>,
        ) {
            let Some((_, info)) = state.toplevels.iter_mut().find(|(h, _)| h == proxy) else {
                return;
            };
            match event {
                zwlr_foreign_toplevel_handle_v1::Event::Title { title } => {
                    info.title = Some(title);
                }
                zwlr_foreign_toplevel_handle_v1::Event::AppId { app_id } => {
                    info.app_id = Some(app_id);
                }
                zwlr_foreign_toplevel_handle_v1::Event::State { state: raw } => {
                    // wl_array serialised as little-endian uint32 entries; value 2 = activated
                    info.activated = raw
                        .chunks(4)
                        .any(|b| b.len() == 4 && u32::from_ne_bytes([b[0], b[1], b[2], b[3]]) == 2);
                }
                _ => {}
            }
        }
    }

    // ── connect and roundtrip ────────────────────────────────────────────────

    let conn = Connection::connect_to_env()?;
    let mut eq = conn.new_event_queue::<WlrState>();
    let qh = eq.handle();
    let mut state = WlrState::default();

    conn.display().get_registry(&qh, ());
    eq.roundtrip(&mut state)?;

    if state.manager.is_none() {
        return Ok(None);
    }

    // First roundtrip: receive Toplevel events (creates handles).
    // Second roundtrip: receive Title/AppId/State/Done events on each handle.
    eq.roundtrip(&mut state)?;
    eq.roundtrip(&mut state)?;

    let active = state
        .toplevels
        .into_iter()
        .find(|(_, t)| t.activated)
        .map(|(_, t)| crate::protocol::WindowInfo {
            app_id: t.app_id.unwrap_or_default(),
            title: t.title.unwrap_or_default(),
            pid: None,
        });

    Ok(active)
}
