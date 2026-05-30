# YazSes Privacy Statement

**Last updated: 2026-05-19**
**Applies to: YazSes v0.4.0 and later**

---

## Summary

YazSes is designed from the ground up to keep your voice and text on your device. By default, no audio, transcripts, editor context, or usage data ever leave your machine. There is no cloud dependency, no telemetry, and no account required.

---

## 1. Audio

Audio is captured from your microphone only while you hold the designated hotkey (or squeeze your EMG device). It is held in a short in-memory ring buffer, fed directly to the on-device transcription model, and then discarded. Audio is never written to disk, never logged, and never transmitted anywhere.

---

## 2. Transcription (Speech-to-Text)

Transcription runs entirely on your device using a locally stored model (Moonshine v2 or Whisper.cpp, depending on your configuration). The model weights are downloaded once to `~/.local/share/yazses/models/` (Linux), `~/Library/Application Support/yazses/models/` (macOS), or `%APPDATA%\yazses\models\` (Windows) and run offline thereafter.

The resulting transcript is held in memory long enough to inject text and, when Personal Memory is enabled, to evaluate whether a remember command was spoken. The transcript is not written to any log file and is not transmitted anywhere.

---

## 3. Personal Memory Database

Personal Memory is **opt-in** and disabled by default. When enabled, YazSes stores only the memories you explicitly dictate (for example, "remember that my project uses Python 3.12"). Nothing is stored automatically.

**Storage location:**

| Platform | Path |
|---|---|
| Linux | `~/.local/share/yazses/memory.db` |
| macOS | `~/Library/Application Support/yazses/memory.db` |
| Windows | `%APPDATA%\yazses\memory.db` |

**Encryption:** The database is an encrypted SQLite file (SQLCipher). The encryption key is derived from your passphrase using PBKDF2. YazSes never stores your passphrase in plaintext. After five consecutive incorrect passphrase attempts, access is locked for 15 minutes to limit brute-force attacks.

**Deletion:** To permanently erase all stored memories, delete `memory.db` at the path above. There is no cloud backup and no way for Anthropic or any third party to recover deleted memories.

---

## 4. Configuration File

YazSes reads a TOML configuration file at startup:

| Platform | Path |
|---|---|
| Linux | `~/.config/yazses/config.toml` |
| macOS | `~/Library/Application Support/yazses/config.toml` |
| Windows | `%APPDATA%\yazses\config.toml` |

This file contains your personal preferences (hotkey, microphone device, model selection, optional EMG port, and so on). It is read locally and never transmitted anywhere.

---

## 5. IPC (Inter-Process Communication)

The YazSes daemon communicates with the CLI and tray application through a local socket:

- **Linux / macOS:** Unix domain socket at `~/.local/share/yazses/yazses.sock`
- **Windows:** Named pipe

The IPC channel is strictly localhost-only. YazSes does not open any network port or listen on any external interface.

---

## 6. Editor Context

When the LSP context feature is enabled (`lsp_enabled = true` in config), YazSes reads the active file path, programming language, and cursor line from your editor. This information is used only as a prefix to the transcription prompt so that the speech-to-text model can produce context-aware output (for example, recognising code identifiers from your current file).

Editor context is never transmitted outside your device and is discarded after each transcription.

---

## 7. Local LLM (llama.cpp / Ollama)

When an LLM backend is configured, YazSes sends text (your spoken command, relevant memory fragments, and editor context) to a locally running model via llama.cpp or the Ollama API at `localhost:11434`. This communication never leaves your machine.

---

## 8. Opt-in OpenAI-Compatible Backend

YazSes includes optional support for an OpenAI-compatible LLM API (for example, OpenAI, Azure OpenAI, or a compatible self-hosted endpoint). **This feature is never active by default.** It is a compile-time feature gate that requires explicit configuration:

```toml
[llm]
backend = "openai"
base_url = "https://api.openai.com/v1"
api_key  = "sk-..."
```

If you configure this backend, your spoken commands and any relevant memory fragments will be sent to the endpoint you specify. You are responsible for reviewing the privacy policy of that third-party service before enabling this feature. YazSes itself does not control how that service handles your data.

If you do not set `backend = "openai"` in your config, no data is ever sent to OpenAI or any other external API.

---

## 9. Remote Mode (`yazses remote <host>`)

Remote mode forwards your audio and transcripts over an SSH tunnel to a host you control. The target host is always specified explicitly by you on the command line; YazSes never connects to any host automatically or without your instruction.

Data in transit is protected by SSH encryption. No third-party relay server is involved. The remote host runs `yazses-agent`, which performs text injection on that machine. Ensure you trust and control the remote host before using this feature.

---

## 10. What Leaves Your Device

The table below summarises data flows under each configuration:

| Data | Default (local-only) | Remote mode | OpenAI backend enabled |
|---|---|---|---|
| Audio | Stays on device | Forwarded over SSH to your remote host | Stays on device |
| Transcripts | Stays on device | Forwarded over SSH to your remote host | Sent to the configured API endpoint |
| Editor context | Stays on device | Not forwarded | May be sent to the configured API endpoint |
| Personal memories | Stays on device | Not forwarded | May be sent to the configured API endpoint |
| Usage statistics / telemetry | Never collected | Never collected | Never collected |

In the default configuration, **nothing leaves your device**.

---

## 11. Telemetry, Analytics, and Update Checks

YazSes collects no telemetry, no usage analytics, and no crash reports. It performs no automatic update checks and makes no outbound network connections unless you have explicitly configured a remote host or an external LLM backend.

---

## 12. Third-Party Dependencies

YazSes depends on open-source libraries (faster-whisper, llama.cpp, SQLCipher, sounddevice, and others). These libraries run entirely on your device and do not make independent network requests. You can audit their source code through the links in the project's dependency manifest (`pyproject.toml`).

---

## 13. Your Rights and Controls

| Action | How |
|---|---|
| Disable Personal Memory | Remove or do not set the `[memory]` section in `config.toml` |
| Erase all stored memories | Delete `memory.db` at the path listed in Section 3 |
| Disable LSP editor context | Set `lsp_enabled = false` in `config.toml` (the default) |
| Stop using an external LLM | Remove `[llm]` or set `backend = "local"` in `config.toml` |
| Inspect stored data | Open `memory.db` with any SQLCipher-compatible tool after unlocking with your passphrase |

Because all data is stored locally and no account is required, there is no server-side data to request deletion of. You have full control over every file YazSes writes.

---

## 14. Contact

YazSes is an open-source project. If you find a privacy concern or a discrepancy between this statement and the actual behaviour of the software, please open an issue on the project's GitHub repository so it can be investigated and corrected.
