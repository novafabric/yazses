# YazSes

[![Tests](https://github.com/novafabric/yazses/actions/workflows/test.yml/badge.svg)](https://github.com/novafabric/yazses/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/yazses)](https://pypi.org/project/yazses/)
[![Get it from the Snap Store](https://snapcraft.io/en/dark/install.svg)](https://snapcraft.io/yazses)
[![Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Rust](https://img.shields.io/badge/rust-1.85%2B-orange.svg)](https://www.rust-lang.org/)

Hold a key, speak, release — the on-device AI agent understands and acts: typing text, running git commands, controlling media, opening files, querying your personal memory — all without a cloud.

```
Hold hotkey (>0.5 s) → audio → STT → on-device LLM → dispatch one of 20 OS tools → result in focused window
```

Powered by [whisper.cpp](https://github.com/ggerganov/whisper.cpp) (STT) + [llama.cpp](https://github.com/ggerganov/llama.cpp) (LLM) on CPU. Works in browsers, terminals, IDEs, chat apps, any app. Offline. Private.

---

## What YazSes does

When you hold the hotkey, YazSes captures audio and passes it through an on-device STT model. The transcript is handed to a local LLM (no API key, no network request) which selects one of 20 OS-level tools and calls it with extracted parameters. The result appears in the focused window within one second on a modern laptop. Nothing leaves the machine.

**20 built-in tools:**

| Tool | What it does |
|---|---|
| `type_text` | Insert transcribed text at cursor |
| `key_sequence` | Send an arbitrary key chord (Ctrl+S, etc.) |
| `git_commit` | Stage all changes and commit with a spoken message |
| `open_file` | Open a file path spoken aloud |
| `goto_symbol` | Jump to a named function or class via LSP |
| `volume_set` | Set system audio volume to a spoken level |
| `media_play_pause` | Toggle media playback |
| `screenshot_named` | Take a screenshot with a spoken filename |
| `note_quick` | Append a timestamped note to the daily note file |
| `time_set_timer` | Set a countdown timer with a spoken duration |
| `window_focus` | Bring a named application window to the foreground |
| `app_launch` | Launch an application by name |
| `dismiss_notification` | Dismiss the topmost desktop notification |
| `commit_to_memory` | Store a spoken fact in the encrypted local memory store |
| `recall` | Query the local memory store with a spoken question |
| `forget_last` | Delete the most recently committed memory entry |
| `clarify` | Ask the agent to repeat or rephrase what it heard |
| `send_message` | Compose and send a message via a configured messenger |
| `mode_switch` | Switch the active voice profile (dictation / command / code) |
| `cancel_request` | Abort the current agent action |

---

## Supported platforms

| OS      | Hotkey default | Install                                            | v1.0 Rust | v0.4.x Python |
|---------|----------------|----------------------------------------------------|-----------|---------------|
| Linux   | `Space`        | apt / snap / PPA / AUR / .deb / pipx              | Stable    | Stable        |
| macOS   | `Right Option` | `.dmg` / Homebrew Cask                             | Preview   | Stable        |
| Windows | `Right Ctrl`   | `.exe` installer / winget                          | Preview   | Stable        |

> **Why Right Ctrl on Windows, not Right Alt?** On many international layouts Right Alt acts as **AltGr** — used to type `@`, `€`, `{}`, `[]`, `\`, `~`, etc. Hijacking it would break normal typing. Right Ctrl is rarely used for typing, so it is the safer default. Every platform's hotkey is configurable in `config.toml`.

---

## Requirements

- **OS:** Linux (primary), macOS 13+, Windows 10+
- **RAM:** 16 GB recommended; 8 GB usable with Phi-4-mini Q4_K_M
- **Disk:** 6–10 GB for the default model (Qwen3-7B-Instruct Q4_K_M)
- **CPU:** 4+ cores; no GPU required
- **Microphone:** any USB or built-in microphone
- **Linux text injection:** one of xdotool (X11), wtype (Wayland), or ydotool (Wayland)

---

## Quick install

```sh
# macOS  — via Homebrew tap
brew tap novafabric/yazses && brew install --cask yazses

# Windows  — via winget (pending PR review at microsoft/winget-pkgs#371427)
winget install NovaFabric.YazSes

# Linux  — via the apt repo
bash <(curl -fsSL https://raw.githubusercontent.com/novafabric/yazses/main/install.sh)

# Cross-platform fallback — pip
pipx install yazses
```

The Rust binary is the v1.0 default for all installers above. The Python v0.4.x path remains available via `uv run yazses` (from source) or `pipx install "yazses<1.0"`.

After install:

| OS      | What's left |
|---------|-------------|
| macOS   | Right-click → Open the first time (unsigned dev preview); grant **Accessibility** + **Microphone** when prompted; hold **Right Option** to dictate. |
| Windows | If SmartScreen warns, click **More info → Run anyway** (unsigned dev preview); hold **Right Ctrl** to dictate. |
| Linux   | `sudo usermod -aG input "$USER"` then re-login; `systemctl --user enable --now yazses.service`; hold **Space** to dictate. |

---

## First use

```sh
yazses doctor               # check OS prerequisites
yazses model pull qwen3-7b  # download default LLM (~5 GB, Qwen3-7B-Instruct Q4_K_M)
yazses enroll               # calibrate VAD for your microphone
yazses start
# Hold Space (Linux) or the configured hotkey, speak, release.
```

---

## Key features

- **Sub-second on-device agent loop** — hold to act under 1 s P50 on a modern laptop; no cloud round-trip
- **20 OS-level tools** — type text, commit code, control media, take screenshots, set timers, take notes, and more
- **Dual-stack STT** — Moonshine v2 (~9 ms, streaming) for short utterances; Whisper-large-v3-turbo for long-form
- **Editor LSP bridge** — Neovim and VS Code context injected into both ASR (vocabulary biasing) and LLM (symbol-aware suggestions); improves accuracy on camelCase and snake_case identifiers spoken aloud
- **Personal memory** — encrypted SQLite vector store; voice-triggered commit/recall/forget
- **Zero telemetry, zero cloud by default** — OpenAI-compatible backend is opt-in
- **Accessibility** — AT-SPI (Linux) and NVDA (Windows) screen-reader announcements; Talon coexistence file auto-generated

---

## Configuration

`config.toml` lives in the platform's standard config directory:

| OS      | Path |
|---------|------|
| Linux   | `~/.config/yazses/config.toml` |
| macOS   | `~/Library/Application Support/yazses/config.toml` |
| Windows | `%APPDATA%\yazses\config.toml` |

Key fields:

```toml
[hotkey]
key = "auto"               # "auto" → Space (Linux) / right_option (macOS) / right_ctrl (Windows)
hold_threshold_ms = 500

[llm]
model_path = ""            # path to a GGUF model; empty = use the model pulled by `yazses model pull`

[stt]
backend = "auto"           # "moonshine" (fast, streaming) | "whisper" (long-form) | "auto"

[audio]
device = ""                # empty = system default microphone

[memory]
passphrase = ""            # empty = unencrypted; set a passphrase to enable encryption
```

A complete reference is in the [CLI reference](docs/cli-reference.md).

### Tuning the silence threshold

If dictation does nothing and the daemon logs `Silent audio -- discarding`, your
speech is below the VAD gate (`accessibility.vad_threshold`). Measure your voice
and apply a fitting threshold:

```sh
yazses mic-level          # record ~4s, print your level + a recommendation
yazses mic-level --set    # same, and write the recommendation to config.toml
yazses stop && yazses start   # restart to apply
```

Speak in your normal voice during the countdown. Lower the threshold for quiet
speech; raise it if background noise produces spurious text. Re-run any time your
speaking volume changes (e.g. quiet late-night dictation).

---

## Distribution channels

#### macOS

```sh
# Homebrew Cask (primary)
brew tap novafabric/yazses && brew install --cask yazses

# Direct .dmg download (no Homebrew needed)
# https://github.com/novafabric/yazses/releases/latest
```

#### Windows

```powershell
# winget (pending review)
winget install NovaFabric.YazSes

# Direct .exe download
# https://github.com/novafabric/yazses/releases/latest
```

#### Linux

```bash
# APT repo (Debian/Ubuntu) — v1.0 Rust binary
curl -fsSL https://novafabric.github.io/yazses/apt/KEY.gpg \
  | sudo gpg --dearmor --yes -o /usr/share/keyrings/yazses.gpg
echo "deb [signed-by=/usr/share/keyrings/yazses.gpg] https://novafabric.github.io/yazses/apt ./" \
  | sudo tee /etc/apt/sources.list.d/yazses.list
sudo apt update && sudo apt install yazses

# Launchpad PPA (Ubuntu) — v1.0 Rust binary
sudo add-apt-repository ppa:novafabric/yazses
sudo apt update && sudo apt install yazses

# Snap (most distros with snapd) — v1.0 Rust binary
sudo snap install yazses --classic

# AUR (Arch / Manjaro / EndeavourOS) — v1.0 Rust binary
yay -S yazses

# .deb download
# https://github.com/novafabric/yazses/releases/latest
sudo apt install ./yazses_*.deb

# pipx — Python v0.4.x
sudo apt install libportaudio2 xdotool xclip pipx
pipx install yazses
```

---

## Documentation

| Document | Contents |
|---|---|
| [`docs/install-linux.md`](docs/install-linux.md) | Linux detailed install guide (apt, snap, PPA, AUR, pipx) |
| [`docs/macos-install.md`](docs/macos-install.md) | macOS detailed install guide (Gatekeeper, Accessibility, Microphone) |
| [`docs/windows-install.md`](docs/windows-install.md) | Windows detailed install guide (SmartScreen, antivirus, privacy) |
| [`docs/cli-reference.md`](docs/cli-reference.md) | Full CLI reference — all commands and flags |
| [`docs/plugin-sdk.md`](docs/plugin-sdk.md) | Plugin SDK — adding custom tools and voice commands |
| [`docs/privacy-statement.md`](docs/privacy-statement.md) | What data stays on-device, what is never collected |
| [`docs/migration-v04-to-v10.md`](docs/migration-v04-to-v10.md) | Migrating from Python v0.4.x to Rust v1.0 |

---

## Development

### Rust (v1.0 — default)

```bash
git clone https://github.com/novafabric/yazses
cd yazses
cargo build                          # default features, no native ML libs needed for dev
cargo test --workspace               # 94 tests
```

Feature flags for optional backends:

| Flag | Enables |
|---|---|
| `--features whisper` | whisper.cpp STT backend via whisper-rs |
| `--features moonshine` | Moonshine v2 streaming STT backend |
| `--features llama-cpp` | llama.cpp LLM backend (GBNF tool calls) |
| `--features ollama` | Ollama HTTP LLM backend |
| `--features silero` | Silero VAD (neural, replaces RMS gate) |

### Python v0.4.x

```bash
uv sync
uv run pytest tests/ -v   # 246 tests across all platforms
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

If YazSes is useful to you, a ⭐ on GitHub and a mention in your project, blog, or talk is the best way to support continued development.
