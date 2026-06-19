# CLI Reference (Python v0.4 line)

All commands are available as `yazses <command>` once installed globally
(`uv tool install` / `pipx install`), or as `uv run yazses <command>` from the
repo.

**Getting help.** Every command and subcommand accepts both `-h` and `--help`;
each shows its options plus an **Examples** block. `yazses --help` lists all
commands grouped into panels (Daemon, Setup & calibration, Dictation &
correction, Remote, Learning & tuning); bare `yazses` shows the same help.
`yazses --version` / `-V` prints the version.

**Tab completion.** Run `yazses --install-completion` once to enable `<Tab>`
completion of commands and options in your shell (`yazses --show-completion`
prints the script to inspect or customise).

## Daemon lifecycle

| Command | Description |
|---|---|
| `yazses start` | Start the daemon detached (PID-file tracked). Under systemd, prefer `systemctl --user start yazses`. |
| `yazses stop` | Stop the running daemon (SIGTERM). |
| `yazses status` | Show state, hotkey, model, injection backend, uptime (over IPC). |
| `yazses-daemon` | Run the daemon in the **foreground** (logs to console) — useful for debugging. |

## Updating

| Command | Description |
|---|---|
| `yazses update` | Check for a newer version and offer to install it. Detects the install method and checks the matching source — the tracked **snap** channel for snap installs, **PyPI** for pip / pipx / uv-tool. Only upgrades when the available version is strictly newer (never a downgrade). |
| `yazses update --check` | Only report what's available; don't install. |
| `yazses update --yes` | Install the update without prompting. |

After a successful update, restart the daemon to load it:
`systemctl --user restart yazses` (or `yazses stop && yazses start`).

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
| `yazses punch-in` | Re-speak just the wrong phrase to correct the last dictation burst. Records a short window, aligns it against the last burst, deletes it and retypes it corrected. Requires `[punch_in] enabled = true`. |
| `yazses punch-in --dry-run` | List candidate spans without editing, so you can confirm first. |
| `yazses punch-in --choose N` | Apply the candidate at rank `N` (0 = best match). |

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
| `yazses tune` | Analyse the captured corpus and **print** proposed config diffs (vocabulary, `vad_threshold`, model, disfluency rules, SLM few-shots). Each proposal is checked against a recent **held-out** slice of the corpus and labelled *validated (N/M held-out)* / *unverified* / *unvalidated (corpus too small)* (ADR-014); corroborated proposals are listed first. Dry-run; changes nothing. |
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

## Voice macros (Say-Macro)

Off by default. Enable in `config.toml`, then define triggers in a sibling
`macros.toml`:

```toml
# config.toml
[macros]
enabled = true
author  = "Your Name"      # value substituted for ${author}
path    = "macros.toml"    # relative to the config dir, or absolute
```

```toml
# macros.toml — speak the trigger alone to expand it
[[macro]]
trigger = "license header"
type    = "text"
text    = "# SPDX-License-Identifier: MIT\n# Copyright (c) ${date} ${author}\n"

[[macro]]
trigger = "try except"
type    = "snippet"        # ${cursor} marks where the caret lands after expansion
snippet = "try:\n    ${cursor}\nexcept Exception as exc:\n    raise"
```

- **Matching is whole-utterance exact** (case/whitespace/trailing-punctuation
  insensitive): saying *"license header"* on its own fires; saying it inside a
  sentence does not, so macros never trigger mid-dictation.
- A macro takes precedence over a built-in command of the same phrase.
- **Placeholders:** `${cursor}` (snippet caret, first occurrence), `${date}`
  (`YYYY-MM-DD`), `${time}` (`HH:MM`), `${author}` (from config), `${clipboard}`.
  Unknown `${...}` tokens are left literal. No shell/command execution.
- `type = "actions"` (OS/app key chains) is parsed but dormant in this release
  (lands in P2).

## Mid-Thought Undo

On by default (`[revise] enabled = true`). Say **"scratch that"** (or "delete
that" / "no scratch that") as a whole utterance to delete the last thing YazSes
typed — it issues backspaces, so it works in any text field, and a buffer ledger
ensures it never deletes more than YazSes injected. Saying the phrase inside a
sentence ("scratch the surface") does not trigger it. Disable with
`[revise] enabled = false`.

## Punch-In — correct by re-speaking (off by default)

Enable with `[punch_in] enabled = true`. Run `yazses punch-in`, re-speak just the
wrong phrase, and YazSes locates the closest span in the last burst it typed
(stdlib `difflib`), deletes that burst, and retypes it corrected. Because pure
respeak fixes only ~35% on the first try (Suhm 2001), the alignment surfaces the
top candidates rather than silently splicing — use `--dry-run` to review them and
`--choose N` to apply a specific span.

```toml
[punch_in]
enabled = true
min_score = 0.5         # minimum difflib similarity to surface a span
max_candidates = 3
record_seconds = 4.0    # re-record window for the respoken phrase
```

## Prosody Ink — prosody-driven formatting (off by default, batch dictation only)

Enable with `[prosody] enabled = true`. A long inter-word pause becomes a
paragraph break; with `format = "markdown"` and the `prosody` extra
(`uv sync --extra prosody` → parselmouth) vocal emphasis becomes **bold**.
`format = "none"` keeps paragraph breaks (universal whitespace) and drops bold.
Dictation only; skipped on the streaming path. When enabled, `yazses doctor`
reports whether the `prosody` extra is importable (WARN if missing — pause→¶ still
works, only emphasis is disabled).

```toml
[prosody]
enabled = true
format = "markdown"        # none | markdown
pause_paragraph_ms = 700
emphasis_enabled = true
emphasis_sensitivity = 0.65
max_latency_ms = 150       # above this, logs a warning and degrades to pause-only
```

## Dysfluency-Friendly Mode — clean stuttered / dysarthric dictation (off by default)

Enable with `[accessibility] dysfluency_friendly = true`. The disfluency filter then
collapses sub-word repetitions (`b-b-because` → `because`), short fragment runs
(`b b because` → `because`), heavy unigram repeats (`the the the` → `the`), and
prolongations (`sooo` → `so`) out of the final text — while protecting proper nouns,
code identifiers, URLs, intentional hyphenation (`re-read`), and emphasis (`very very`).
It also widens pre-speech padding for delayed voice onset. It does **not** change
endpointing: YazSes is hold-to-talk, so you control when the utterance ends (ADR-015).
Fully offline, no model training. When on, `yazses doctor` shows the mode's status.

```toml
[accessibility]
dysfluency_friendly = true     # one switch: enables the collapse pass + wider onset padding

# Fine-grained knobs (set individually instead of the preset if you prefer):
[filters.disfluency]
collapse_repetitions = true        # b-b-because / b b because / the the the
collapse_prolongations = true      # sooo -> so
prolongation_min_run = 3           # letter-run length that triggers collapse
repetition_max_fragment_len = 2    # max length of a stutter "fragment"
```

## Ghost Ahead — endpoint pre-warm (off by default)

Enable with `[endpoint] enabled = true`. The daemon predicts *when* you stop
(stable confirmed prefix + trailing silence) and pre-warms the decode path to hide
release latency. Pre-warm is harmless — the authoritative transcript still happens
on real hold-release, so a wrong guess can never truncate text. Speculative
finalize stays gated behind `speculative_finalize` (Phase 2).

```toml
[endpoint]
enabled = true
prewarm = true
debounce_ms = 500          # anti-thrash between endpoint fires
```

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
