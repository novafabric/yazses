# Installing YazSes on Linux (Python v0.4 line)

This guide installs the Python daemon as a global command and starts it
automatically at login. It targets the reliable batch (transcribe-on-release)
configuration. Tested on X11 + PipeWire.

## 1. Prerequisites

```bash
yazses doctor   # after install, but the checks apply: xdotool, mic, input group
```

- **`xdotool`** (X11) or **`ydotool`/`wtype`** (Wayland) for text injection.
- Membership in the **`input`** group so the daemon can read the keyboard via
  evdev: `sudo usermod -aG input "$USER"` then log out/in.
- A working microphone (PipeWire/PulseAudio/ALSA).

## 2. Install the CLI globally

The project ships as a Python package. Install it isolated so `yazses` works
from anywhere. Either tool works — `uv tool` if you already use `uv`, otherwise
`pipx`:

```bash
# Option A — uv (recommended if uv is installed)
uv tool install --force /path/to/yazses

# Option B — pipx
pipx install /path/to/yazses
```

This installs four commands: `yazses`, `yazses-daemon`, `yazses-tray`,
`yazses-agent` into `~/.local/bin` (make sure that's on your `PATH`).

> If an old `alias yazses=...` exists in your shell rc pointing at a previous
> build, remove it so the installed binary is used.

## 3. Start at login (systemd user service)

Create `~/.config/systemd/user/yazses.service`:

```ini
[Unit]
Description=YazSes offline voice dictation daemon
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=%h/.local/bin/yazses-daemon
Restart=on-failure
RestartSec=2
# X11 injection (xdotool) needs the display + auth cookie of the active session.
# Match these to your session — check with: echo $DISPLAY ; echo $XAUTHORITY
Environment=DISPLAY=:1
Environment=XAUTHORITY=/run/user/1000/gdm/Xauthority
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=default.target
```

Enable and start it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now yazses.service
systemctl --user status yazses.service     # should be "active (running)"
```

> **Important:** `DISPLAY`/`XAUTHORITY` must match your live session or injected
> text goes nowhere. On X11 they are usually `:0`/`:1` and a GDM `Xauthority`
> path. On Wayland, set `WAYLAND_DISPLAY` instead and use `ydotool`/`wtype`.

## 4. Use it

1. Focus any text field.
2. Hold the hotkey (default `right_alt`), speak, release.
3. The transcript types in once.

```bash
yazses status      # state, hotkey, model, backend
yazses logs        # recent diagnostic log (metadata only)
```

## 5. Tune the silence threshold

If dictation does nothing and `yazses logs` shows `Silent audio -- discarding`,
your speech is below the VAD gate. Measure and set it:

```bash
yazses mic-level --set      # records ~4s; writes a fitting vad_threshold
systemctl --user restart yazses.service
```

Re-run whenever your speaking volume changes (e.g. quiet late-night dictation).

## 6. Manage the service

```bash
systemctl --user restart yazses.service    # after a config change
systemctl --user stop yazses.service       # stop
systemctl --user disable --now yazses.service   # stop + remove autostart
journalctl --user -u yazses.service -f     # live logs via journald
```

Config lives at `~/.config/yazses/config.toml`. See the
[CLI reference](cli-reference.md) for all commands.

## 7. (Optional) Voice-activity overlay

The overlay draws neon "sonar" rings near the cursor that pulse with your voice
while you dictate. Install the extra and enable it:

```bash
uv tool install 'yazses[overlay]'     # adds PySide6
```

```toml
# ~/.config/yazses/config.toml
[overlay]
enabled = true
```

The daemon auto-launches `yazses-overlay` on start when a display is present and
terminates it on shutdown. Run `yazses overlay` yourself to preview it.

**Transparency note (X11):** the see-through glow needs a compositing window
manager. If you run a bare WM without one, install `picom`:

```bash
sudo apt install picom && picom -b      # or enable your DE's compositor
```

Without a compositor the rings still render, just on a small opaque panel.

To autostart it as its own user service instead of letting the daemon spawn it,
create `~/.config/systemd/user/yazses-overlay.service` with
`ExecStart=%h/.local/bin/yazses-overlay`, `Environment=DISPLAY=:0`, and
`After=yazses.service`, then `systemctl --user enable --now yazses-overlay`.
