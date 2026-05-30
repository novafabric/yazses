/// X11 EWMH window detector — tier 4 of the four-tier WindowDetector (adr-006).
///
/// Works on any X11 window manager that implements the EWMH spec
/// (`_NET_ACTIVE_WINDOW`, `WM_CLASS`, `_NET_WM_NAME`).
/// **Feature gate:** `--features x11`
pub struct X11EwhmWindowDetector;

impl X11EwhmWindowDetector {
    #[cfg(all(target_os = "linux", feature = "x11"))]
    pub async fn try_connect() -> Option<Self> {
        if std::env::var("DISPLAY").is_ok() {
            Some(Self)
        } else {
            None
        }
    }
}

#[cfg(all(target_os = "linux", feature = "x11"))]
#[async_trait::async_trait]
impl crate::protocol::WindowDetector for X11EwhmWindowDetector {
    fn name(&self) -> &str {
        "x11-ewmh"
    }

    async fn focused_window(&self) -> anyhow::Result<Option<crate::protocol::WindowInfo>> {
        tokio::task::spawn_blocking(query_focused_x11)
            .await
            .map_err(|e| anyhow::anyhow!("X11 task join: {e}"))?
    }
}

#[cfg(all(target_os = "linux", feature = "x11"))]
fn query_focused_x11() -> anyhow::Result<Option<crate::protocol::WindowInfo>> {
    use x11rb::connection::Connection;
    use x11rb::protocol::xproto::{self, AtomEnum, ConnectionExt};
    use x11rb::rust_connection::RustConnection;

    let (conn, screen_num) = RustConnection::connect(None)?;
    let root = conn.setup().roots[screen_num].root;

    // Intern the atoms we need.
    let atom_active = conn
        .intern_atom(false, b"_NET_ACTIVE_WINDOW")?
        .reply()?
        .atom;
    let atom_wm_name = conn.intern_atom(false, b"_NET_WM_NAME")?.reply()?.atom;
    let atom_utf8 = conn.intern_atom(false, b"UTF8_STRING")?.reply()?.atom;

    // Get the active window XID.
    let prop = conn
        .get_property(false, root, atom_active, AtomEnum::WINDOW, 0, 1)?
        .reply()?;

    let window = match prop.value32().and_then(|mut it| it.next()) {
        Some(w) if w != 0 => w,
        _ => return Ok(None),
    };

    // Get WM_CLASS: null-separated "instance\0class\0" in ASCII.
    let class_prop = conn
        .get_property(
            false,
            window,
            xproto::AtomEnum::WM_CLASS,
            AtomEnum::STRING,
            0,
            256,
        )?
        .reply()?;
    let raw = String::from_utf8_lossy(&class_prop.value);
    // Second null-separated token is the class name.
    let app_id = raw
        .split('\0')
        .nth(1)
        .unwrap_or("")
        .trim_end_matches('\0')
        .to_string();

    // Get _NET_WM_NAME (UTF-8 title).
    let name_prop = conn
        .get_property(false, window, atom_wm_name, atom_utf8, 0, 256)?
        .reply()?;
    let title = String::from_utf8_lossy(&name_prop.value)
        .trim_end_matches('\0')
        .to_string();

    Ok(Some(crate::protocol::WindowInfo {
        app_id,
        title,
        pid: None,
    }))
}
