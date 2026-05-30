# CLI Reference (Python v0.4 line)

All commands are available as `yazses <command>` once installed globally
(`uv tool install` / `pipx install`), or as `uv run yazses <command>` from the
repo. Run `yazses --help` or `yazses <command> --help` for full option text.

## Daemon lifecycle

| Command | Description |
|---|---|
| `yazses start` | Start the daemon detached (PID-file tracked). Under systemd, prefer `systemctl --user start yazses`. |
| `yazses stop` | Stop the running daemon (SIGTERM). |
| `yazses status` | Show state, hotkey, model, injection backend, uptime (over IPC). |
| `yazses-daemon` | Run the daemon in the **foreground** (logs to console) — useful for debugging. |

## Diagnostics & tuning

| Command | Description |
|---|---|
| `yazses doctor` | Check prerequisites: platform, keyboard capture, microphone, session type, injection tools, model cache, config dir, (EMG port if configured). |
| `yazses mic-level` | Record ~4s, report your average mic level vs the current `vad_threshold`, and recommend a threshold. |
| `yazses mic-level --set` | Same, and write the recommended `vad_threshold` to `config.toml` in place (comments preserved). |
| `yazses mic-level -s N` | Record for `N` seconds instead of 4. |
| `yazses logs` | Print the last 40 lines of the diagnostic log (**metadata only** — never your dictated text). |
| `yazses logs -n N` | Show the last `N` lines. |
| `yazses logs --path` | Print the log file path only (`~/.local/state/yazses/log/daemon.log`). |

## Dictation & injection

| Command | Description |
|---|---|
| `yazses inject "text"` | Inject text into the focused app without recording (tests the injection backend). |
| `yazses enroll` | Run the accessibility calibration wizard (writes `vad_threshold`, etc.). Note: can set a too-high threshold in a noisy room — verify with `yazses mic-level`. |

## Voice-activity overlay (sonar)

A standalone process that draws neon "sonar" rings near the cursor, expanding and
pulsing with your live voice level while you dictate. Requires the `overlay`
extra (PySide6): `uv sync --extra overlay` or `pip install 'yazses[overlay]'`.
For true see-through rings on X11 you need a compositor (e.g. `picom`) running.

| Command | Description |
|---|---|
| `yazses overlay` | Run the overlay in the foreground (preview/debug). Connects to the running daemon over IPC. |
| `yazses-overlay` | Same, as a direct console script (this is what the daemon auto-launches). |

Enable auto-launch with the daemon by setting `[overlay] enabled = true`. The
daemon only spawns it when a display (`DISPLAY`/`WAYLAND_DISPLAY`) is present.

`[overlay]` config keys:

| Key | Default | Description |
|---|---|---|
| `enabled` | `false` | Auto-launch the overlay alongside the daemon. |
| `style` | `"sonar"` | Visual style (reserved for future styles). |
| `position` | `"cursor"` | `cursor` \| `bottom_center` \| `top_center` \| `corner`. |
| `react_to_voice` | `true` | Drive the animation from live mic level (vs a steady pulse). |
| `accent` | `"#00e5ff"` | Ring colour (neon cyan). |
| `size_px` | `220` | Overlay window square size. |
| `fps` | `60` | Render frame rate. |
| `cursor_offset_px` | `28` | Offset from the pointer (so it isn't under the caret). |

## Remote dictation

| Command | Description |
|---|---|
| `yazses remote <host>` | Forward voice typing to a remote SSH host. `--port/-p`, `--key-file/-i`, `--stop`. |
| `yazses-agent --listen <port>` | Run the remote injection agent on the remote host. |

## Self-improvement loop (opt-in, local, encrypted)

Requires `[learning] enabled = true` (off by default; ADR-012). All data stays
on the machine, encrypted at rest with a machine-bound key.

| Command | Description |
|---|---|
| `yazses tune` | Analyse the captured corpus and **print** proposed config diffs (vocabulary, `vad_threshold`, model, disfluency rules, SLM few-shots). Dry-run; changes nothing. |
| `yazses tune --apply` | Same, but review each proposal interactively and write approved ones to `config.toml` (comments preserved). |
| `yazses tune --no-retranscribe` | Skip the larger-model re-transcription pass (faster; uses only flagged/edited signals). |
| `yazses mark-wrong` | Flag the last dictation as a misrecognition (a learning signal). Routed through the running daemon. |
| `yazses mark-wrong -c "what you said"` | Same, attaching the correct text. |
| `yazses corpus status` | Show corpus location, event/discard/flag counts, size, and date range. |
| `yazses corpus forget --minutes N` | Delete events captured in the last `N` minutes (e.g. after dictating something private). |
| `yazses corpus destroy --i-mean-it` | Irreversibly wipe the corpus (database + audio clips). |

## Models (Tier 2 SLM intent routing)

| Command | Description |
|---|---|
| `yazses model list` | List available / downloaded SLM intent-routing models. |
| `yazses model download <name>` | Download an SLM model. |

## Diagnostic log format

`yazses logs` shows lines like:

```
INFO yazses.core.daemon: Transcribed 2.1s audio in 480 ms (model base.en, level 0.0043)
INFO yazses.core.daemon: Injecting 24 chars, 5 words.
INFO yazses.core.daemon: Silent audio -- discarding (level 0.0009 < vad_threshold 0.0021; run 'yazses mic-level --set' to retune).
```

These are **metadata only** — audio level, latency, model, counts, and errors.
The actual transcript text is logged only when `general.log_level = "DEBUG"` in
`config.toml`.
