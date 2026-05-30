# YazSes

[![Tests](https://github.com/novafabric/yazses/actions/workflows/test.yml/badge.svg)](https://github.com/novafabric/yazses/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/yazses)](https://pypi.org/project/yazses/)
[![Snap Store](https://snapcraft.io/en/dark/install.svg)](https://snapcraft.io/yazses)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Rust 1.85+](https://img.shields.io/badge/rust-1.85%2B-orange.svg)](https://www.rust-lang.org/)

**Hold a key → speak → release.** An on-device AI agent types text, commits code, controls media, takes notes, and more — entirely offline. No cloud. No API key. No subscription.

---

## Quick Start

**Step 1 — Install**

| Platform | Command |
|---|---|
| **Linux** (Debian/Ubuntu) | `bash <(curl -fsSL https://raw.githubusercontent.com/novafabric/yazses/main/install-apt.sh)` |
| **Linux** (any distro) | `pipx install yazses` |
| **macOS** | `brew tap novafabric/yazses && brew install --cask yazses` |
| **Windows** | `winget install NovaFabric.YazSes` |

**Step 2 — Set up**

```sh
yazses doctor               # check everything is ready
yazses model pull qwen3-7b  # download the AI model (~5 GB, one-time)
yazses enroll               # calibrate your microphone (30 seconds)
yazses start                # start the daemon
```

**Step 3 — Use it**

| OS | Hold this key | Say anything |
|---|---|---|
| Linux | `Space` | "open terminal", "commit add new feature", "type hello world" |
| macOS | `Right Option` | "set volume to 50", "take a screenshot called mockup" |
| Windows | `Right Ctrl` | "remember my meeting is at 3pm", "what did I tell you yesterday?" |

Release the key — YazSes acts within one second.

> **First time on macOS?** Right-click the app → Open (Gatekeeper), then grant Accessibility + Microphone when prompted.
>
> **First time on Windows?** If SmartScreen warns you, click **More info → Run anyway**.
>
> **First time on Linux?** Run `sudo usermod -aG input "$USER"` and re-login before starting.

---

## What you can say

YazSes understands natural language and maps it to 20 built-in actions:

| Say something like… | What happens |
|---|---|
| *"type hello world"* | Types text at the cursor |
| *"commit added login feature"* | Runs `git add -A && git commit -m "added login feature"` |
| *"open main.py"* | Opens the file |
| *"go to function parse_config"* | Jumps to the symbol via LSP |
| *"set volume to 30"* | Sets system volume |
| *"take a screenshot called diagram"* | Saves `diagram.png` |
| *"remember my password expires on June 1"* | Stores in encrypted local memory |
| *"what did I remember about passwords?"* | Queries local memory |
| *"set a timer for 25 minutes"* | Starts a countdown |
| *"open VS Code"* | Launches the application |
| *"press Control S"* | Sends the key chord |

---

## How it works

```
Hold hotkey → record audio → speech-to-text → local LLM → pick tool → execute
```

Everything runs on your CPU. The LLM (Qwen3-7B by default) reads the transcript and decides which of the 20 tools to call. Result appears in the focused window within ~1 second on a modern laptop.

**Models used:**
- **STT:** Moonshine v2 (9 ms, streaming) for short commands · Whisper-large-v3-turbo for long dictation
- **LLM:** llama.cpp with GBNF tool-call grammar (Qwen3-7B default) · Ollama backend optional

---

## Requirements

| | |
|---|---|
| **OS** | Linux (primary) · macOS 13+ · Windows 10+ |
| **RAM** | 8 GB minimum · 16 GB recommended |
| **Disk** | 6–10 GB for the default model |
| **CPU** | 4+ cores · no GPU required |
| **Mic** | Any USB or built-in microphone |

---

## Key features

- **Fully offline** — no audio, no text, no data leaves the machine by default
- **Agent, not just dictation** — understands intent, not just words
- **Dual STT stack** — fast streaming for commands, accurate long-form for dictation
- **Personal memory** — encrypted local vector store, voice-queryable
- **Editor integration** — Neovim and VS Code LSP context improves accuracy on code identifiers
- **Accessibility** — AT-SPI (Linux) and NVDA (Windows) screen-reader support; Talon coexistence
- **EMG support** — works with muscle sensors for motor-disability use cases

---

## Configuration

Config file location:

| OS | Path |
|---|---|
| Linux | `~/.config/yazses/config.toml` |
| macOS | `~/Library/Application Support/yazses/config.toml` |
| Windows | `%APPDATA%\yazses\config.toml` |

Essential settings:

```toml
[hotkey]
key = "auto"               # Space (Linux) / right_option (macOS) / right_ctrl (Windows)
hold_threshold_ms = 500    # how long to hold before recording starts

[llm]
model_path = ""            # empty = use the model from `yazses model pull`

[stt]
backend = "auto"           # "moonshine" (fast) | "whisper" (accurate) | "auto"

[audio]
device = ""                # empty = system default microphone

[memory]
passphrase = ""            # set a passphrase to encrypt the memory store
```

See the [CLI reference](docs/cli-reference.md) for all options.

### Microphone not working?

If YazSes does nothing and the log shows `Silent audio -- discarding`:

```sh
yazses mic-level --set   # measure your voice and set the right threshold
yazses stop && yazses start
```

---

## All install options

### Linux

```bash
# APT repo — Debian / Ubuntu (recommended)
bash <(curl -fsSL https://raw.githubusercontent.com/novafabric/yazses/main/install-apt.sh)

# PPA — Ubuntu
sudo add-apt-repository ppa:novafabric/yazses && sudo apt install yazses

# Snap
sudo snap install yazses --classic

# AUR — Arch / Manjaro
yay -S yazses

# pipx (Python v0.4.x)
sudo apt install libportaudio2 xdotool xclip pipx
pipx install yazses
```

### macOS

```sh
# Homebrew Cask (recommended)
brew tap novafabric/yazses && brew install --cask yazses

# Direct download
# https://github.com/novafabric/yazses/releases/latest
```

### Windows

```powershell
# winget (recommended)
winget install NovaFabric.YazSes

# Direct download
# https://github.com/novafabric/yazses/releases/latest
```

---

## Documentation

| | |
|---|---|
| [Install on Linux](docs/install-linux.md) | Detailed Linux guide — permissions, injection backends, service setup |
| [Install on macOS](docs/macos-install.md) | Gatekeeper, Accessibility, Microphone permissions |
| [Install on Windows](docs/windows-install.md) | SmartScreen, antivirus exceptions, privacy settings |
| [CLI reference](docs/cli-reference.md) | All commands and flags |
| [Plugin SDK](docs/plugin-sdk.md) | Adding custom tools and voice commands |
| [Privacy statement](docs/privacy-statement.md) | What stays on-device, what is never collected |
| [Migration v0.4 → v1.0](docs/migration-v04-to-v10.md) | Upgrading from the Python version |

---

## Development

### Rust (v1.0 — default)

```bash
git clone https://github.com/novafabric/yazses
cd yazses
cargo build
cargo test --workspace
```

Optional backends:

| Flag | Enables |
|---|---|
| `--features whisper` | whisper.cpp STT |
| `--features moonshine` | Moonshine v2 streaming STT |
| `--features llama-cpp` | llama.cpp LLM |
| `--features ollama` | Ollama HTTP LLM |
| `--features silero` | Silero neural VAD |

### Python (v0.4.x)

```bash
uv sync
uv run pytest tests/ -v
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

If YazSes is useful to you, a ⭐ on GitHub and a mention in your project, blog, or talk is the best way to support continued development.
