import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SttConfig:
    # base.en balances accuracy and CPU latency far better than tiny.en, which
    # produces frequent word errors. Larger models (small.en/medium.en) trade
    # decode latency for marginal gains on clean speech.
    model: str = "base.en"
    device: str = "cpu"
    compute_type: str = "int8"
    # Optional vocabulary/context primed into Whisper as initial_prompt. Helps it
    # spell domain terms and proper nouns it otherwise mis-transcribes. `yazses
    # tune` proposes additions here from the learning corpus.
    initial_prompt: str = ""


@dataclass
class HotkeyConfig:
    key: str = "space"
    hold_threshold_ms: int = 500
    source: str = "default"
    evdev_device: str = ""


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    channels: int = 1
    max_record_seconds: int = 90


@dataclass
class InjectionConfig:
    backend: str = "auto"
    fallback_to_clipboard: bool = True
    # Successive hold-to-talk bursts within this window are treated as one
    # continuous dictation: a separating space is prepended to the next burst
    # so words don't glue together at the boundary (postprocess/spacing.py).
    # 0 disables continuation spacing entirely.
    continuation_window_ms: int = 30000


@dataclass
class GeneralConfig:
    log_level: str = "INFO"


@dataclass
class StreamingConfig:
    # Disabled by default: live-partial injection corrects on commit via
    # shift+Left selection (inject/streaming.py), which deletes text in apps
    # where shift+Left isn't "extend selection". Batch transcribe-on-release is
    # the reliable, higher-accuracy path proven by tools like nerd-dictation and
    # faster-whisper-dictation. Opt back in with [streaming] enabled = true.
    enabled: bool = False
    partial_interval_ms: int = 300
    partial_marker: str = ""


@dataclass
class DisfluencyConfig:
    enabled: bool = True
    filler_words: list[str] = field(default_factory=lambda: [
        "um", "uh", "er", "err", "ah", "hmm", "like", "you know",
        "i mean", "basically", "right", "okay so",
        "sort of", "kind of", "literally", "actually",
        "so um", "so uh",
    ])
    self_correction_triggers: list[str] = field(default_factory=lambda: [
        "no wait", "delete that", "scratch that", "never mind",
        "forget that", "strike that",
    ])
    # v0.8.0 — Dysfluency-Friendly Mode collapse pass (ADR-015); off by default.
    collapse_repetitions: bool = False      # b-b-because / b b because / the the the
    collapse_prolongations: bool = False    # sooo -> so
    prolongation_min_run: int = 3           # letter-run length that triggers collapse
    repetition_max_fragment_len: int = 2    # max length of a stutter "fragment"
    llm_enabled: bool = False
    llm_endpoint: str = "http://localhost:11434"
    # Local GGUF model path for offline cleanup; empty falls back to the Ollama
    # HTTP endpoint above. Mirrors the Rust v1.0 [cleanup] feature for the
    # Python path (kept in parity until v1.0 GA).
    llm_model: str = ""
    llm_system_prompt: str = (
        "Reformat only. Do not add facts and do not remove information. "
        "Preserve every proper noun, number, code identifier, and URL exactly "
        "as given. Fix capitalization, punctuation, and paragraph breaks; do "
        "not change word choices. Output ONLY the reformatted text with no "
        "preamble, no explanation, and no markdown fences."
    )
    llm_max_tokens: int = 256
    llm_timeout_ms: int = 2000
    llm_min_length_ratio: float = 0.5
    llm_max_length_ratio: float = 2.0


@dataclass
class FiltersConfig:
    disfluency: DisfluencyConfig = field(default_factory=DisfluencyConfig)


@dataclass
class AccessibilityConfig:
    min_silence_ms: int = 500
    pre_speech_padding_ms: int = 200
    vad_source: str = "default"
    vad_threshold: float = 0.01
    # v0.8.0 — Dysfluency-Friendly Mode master preset (ADR-015): enables the
    # disfluency collapse pass and widens onset padding. Off by default.
    dysfluency_friendly: bool = False


@dataclass
class CommandsConfig:
    enabled: bool = True
    profile: str = "auto"
    custom: list[dict] = field(default_factory=list)
    # v0.4.0 — Tier 2 SLM intent routing (ADR-v04-001)
    slm_model_path: str = ""          # path to GGUF file; empty = disabled
    slm_confidence_threshold: float = 0.75
    # v0.4.0 — LSP context injection (ADR-v04-002)
    lsp_enabled: bool = False
    lsp_editor: str = "auto"          # auto | neovim | vscode


@dataclass
class LearningConfig:
    """v0.5.0 — opt-in self-improvement loop (ADR-012).

    OFF by default to honour ADR-011 (zero telemetry, no transcript persistence).
    When enabled, each dictation event is captured to a local, encrypted corpus
    (text stages + optional source audio) that never leaves the machine. The
    `yazses tune` command turns that corpus into proposed config diffs.
    """
    enabled: bool = False
    capture_audio: bool = True
    retention_days: int = 30
    max_corpus_mb: int = 500
    # Larger model used by `yazses tune` to re-transcribe captured audio and
    # produce pseudo-ground-truth for error detection.
    tune_model: str = "small.en"
    # Regexes scrubbed (replaced with [REDACTED]) from text before it is stored.
    redact_patterns: list[str] = field(default_factory=list)
    # Edit capture (signal b): after a dictation, read the editor line back and
    # record what you changed in place. Opt-in, editor-bridge only (NO keystroke
    # logging). Currently supports Neovim via a --listen socket.
    capture_edits: bool = False
    edit_capture_delay_s: float = 8.0
    editor_socket: str = ""           # e.g. nvim --listen /tmp/nvim.sock; empty = disabled


@dataclass
class MacrosConfig:
    """v2 — Say-Macro: user-programmable voice macros (spec-say-macro).

    OFF by default per ADR-011. When enabled, triggers and expansions are read
    from a dedicated ``macros.toml`` (sibling of config.toml); this section only
    carries the switches. P1 supports ``text`` and ``snippet`` expansions matched
    by whole-utterance exact match; OS-action chains land in P2.
    """
    enabled: bool = False
    path: str = "macros.toml"         # relative to config dir, or absolute
    author: str = ""                  # value substituted for ${author}


@dataclass
class ReviseConfig:
    """v2 — Mid-Thought Undo (spec-mid-thought-undo), P1 template layer.

    "scratch that" / "delete that" delete the last YazSes-injected dictation
    burst via backspaces (works in any text field). On by default with the rest
    of the command grammar; open-ended "no, make it X" rewrite is deferred to P2.
    """
    enabled: bool = True


@dataclass
class PunchInConfig:
    """v2 — Punch-In (spec-punch-in), P1 alignment core.

    Re-speak a phrase to correct a span; the daemon/UI surfaces the top aligned
    candidates to confirm (not auto-splice) because pure respeak fixes only ~35%
    (Suhm 2001). OFF by default; the interactive re-record + confirm flow is P2.
    """
    enabled: bool = False
    min_score: float = 0.5            # minimum difflib similarity to surface a span
    max_candidates: int = 3
    record_seconds: float = 4.0       # re-record window for the respoken phrase


@dataclass
class EndpointConfig:
    """v2 — Ghost Ahead -> endpoint anticipation (spec-ghost-ahead), P1 core.

    Predicts *when* the speaker stops (stable partial + trailing silence) to hide
    release latency. OFF by default; the authoritative transcript always stays on
    real hold-release. Phase 1 = harmless pre-warm (eager decode on endpoint);
    speculative finalize (Phase 2) stays gated behind ``speculative_finalize``.
    """
    enabled: bool = False
    min_silence_s: float = 0.3
    stable_updates: int = 2
    prewarm: bool = True              # Phase 1: eagerly decode the buffer on endpoint
    speculative_finalize: bool = False  # Phase 2 (gated): decode early, discardable
    debounce_ms: int = 500           # min gap between endpoint fires (anti-thrash)
    prefix_stable_ms: int = 400      # confirmed prefix unchanged this long = content flat
    falling_window_ms: int = 250     # window over which trailing energy must be falling


@dataclass
class ProsodyConfig:
    """v2 — Prosody Ink (spec-prosody-ink), P1 wired into the dictation pipeline.

    Maps vocal prosody to text formatting: a long inter-word pause becomes a
    paragraph break (Phase 1, no acoustic dep), vocal emphasis becomes bold
    (Phase 2, needs the ``prosody`` extra → parselmouth). OFF by default; batch +
    dictation only. ``format="none"`` keeps the universal pause→¶ whitespace but
    suppresses emphasis (no portable way to express bold in plain text). The
    pitch→question signal stays gated behind ``experimental_pitch_question`` and
    is never built into Phase 1 (acoustically unreliable, ~64.6%; PMC2631211).
    """
    enabled: bool = False
    format: str = "none"              # none | markdown
    pause_paragraph_ms: int = 700     # inter-word gap (ms) at/above which a ¶ is inserted
    emphasis_enabled: bool = True     # bold prominent words (only when format renders bold)
    emphasis_sensitivity: float = 0.65  # 0..1; higher = fewer, surer bolds (precision bias)
    experimental_pitch_question: bool = False
    max_latency_ms: int = 150         # latency valve: above this, log + degrade to pause-only


@dataclass
class RemoteConfig:
    default_host: str = ""
    ssh_port: int = 22
    agent_port: int = 9875
    key_file: str = ""


@dataclass
class EmgConfig:
    """v0.4.0 — EMG silent speech backend (ADR-v04-003).

    v0.4.1 adds ``ble_address`` for wireless BLE transport (same YESP protocol).
    Set either ``device_port`` (USB serial) or ``ble_address`` (BLE), not both.
    """
    device_port: str = ""             # e.g. /dev/ttyUSB0; empty = disabled
    baud_rate: int = 115200
    ble_address: str = ""             # e.g. "AA:BB:CC:DD:EE:FF"; empty = disabled
    mode: str = "command"             # command | full_text
    command_map: dict[str, str] = field(default_factory=dict)


@dataclass
class OverlayConfig:
    """v0.5.0 — futuristic on-screen voice-activity indicator.

    A standalone ``yazses-overlay`` process (separate from the daemon, which is
    blocked by the hotkey loop) draws an animated "sonar" — concentric rings that
    expand near the cursor and pulse with your live mic level while you dictate.
    It is a thin IPC client that polls the daemon's ``status`` RPC, so either the
    Python or the Rust daemon can drive it. Requires the ``overlay`` extra
    (``pip install yazses[overlay]`` / ``uv sync --extra overlay``) for PySide6.
    """
    enabled: bool = False            # auto-launch the overlay with the daemon
    style: str = "sonar"             # reserved for future styles
    position: str = "cursor"         # cursor | bottom_center | top_center | corner
    react_to_voice: bool = True      # amplitude-driven vs state-only self-animation
    accent: str = "#00e5ff"          # ring colour (neon cyan)
    size_px: int = 220               # overlay window square size
    fps: int = 60                    # render tick rate
    cursor_offset_px: int = 28       # offset from the pointer so it isn't under the caret


@dataclass
class Config:
    stt: SttConfig = field(default_factory=SttConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    injection: InjectionConfig = field(default_factory=InjectionConfig)
    general: GeneralConfig = field(default_factory=GeneralConfig)
    streaming: StreamingConfig = field(default_factory=StreamingConfig)
    filters: FiltersConfig = field(default_factory=FiltersConfig)
    accessibility: AccessibilityConfig = field(default_factory=AccessibilityConfig)
    commands: CommandsConfig = field(default_factory=CommandsConfig)
    macros: MacrosConfig = field(default_factory=MacrosConfig)
    revise: ReviseConfig = field(default_factory=ReviseConfig)
    punch_in: PunchInConfig = field(default_factory=PunchInConfig)
    endpoint: EndpointConfig = field(default_factory=EndpointConfig)
    prosody: ProsodyConfig = field(default_factory=ProsodyConfig)
    remote: RemoteConfig = field(default_factory=RemoteConfig)
    emg: EmgConfig = field(default_factory=EmgConfig)
    learning: LearningConfig = field(default_factory=LearningConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)


def _load_filters(data: dict) -> FiltersConfig:
    filters_raw = data.get("filters", {})
    disf_raw = filters_raw.get("disfluency", {})
    return FiltersConfig(disfluency=DisfluencyConfig(**disf_raw))


def _load_emg(data: dict) -> EmgConfig:
    raw = data.get("emg", {})
    return EmgConfig(
        device_port=raw.get("device_port", ""),
        baud_rate=raw.get("baud_rate", 115200),
        ble_address=raw.get("ble_address", ""),
        mode=raw.get("mode", "command"),
        command_map=raw.get("command_map", {}),
    )


def load_config(path: Path | None = None) -> Config:
    if path is None:
        path = Path.home() / ".config" / "yazses" / "config.toml"
    if not path.exists():
        return Config()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    cfg = Config(
        stt=SttConfig(**data.get("stt", {})),
        hotkey=HotkeyConfig(**data.get("hotkey", {})),
        audio=AudioConfig(**data.get("audio", {})),
        injection=InjectionConfig(**data.get("injection", {})),
        general=GeneralConfig(**data.get("general", {})),
        streaming=StreamingConfig(**data.get("streaming", {})),
        filters=_load_filters(data),
        accessibility=AccessibilityConfig(**data.get("accessibility", {})),
        commands=CommandsConfig(**data.get("commands", {})),
        macros=MacrosConfig(**data.get("macros", {})),
        revise=ReviseConfig(**data.get("revise", {})),
        punch_in=PunchInConfig(**data.get("punch_in", {})),
        endpoint=EndpointConfig(**data.get("endpoint", {})),
        prosody=ProsodyConfig(**data.get("prosody", {})),
        remote=RemoteConfig(**data.get("remote", {})),
        emg=_load_emg(data),
        learning=LearningConfig(**data.get("learning", {})),
        overlay=OverlayConfig(**data.get("overlay", {})),
    )
    return _apply_presets(cfg)


def _apply_presets(cfg: Config) -> Config:
    """Apply convenience presets that flip several keys from one switch.

    Dysfluency-Friendly Mode (ADR-015): enable the disfluency collapse pass and
    widen pre-speech padding for delayed voice onset. It does NOT alter
    endpointing — YazSes is hold-to-talk, so the user controls utterance end.
    """
    if cfg.accessibility.dysfluency_friendly:
        cfg.filters.disfluency.collapse_repetitions = True
        cfg.filters.disfluency.collapse_prolongations = True
        cfg.accessibility.pre_speech_padding_ms = max(
            cfg.accessibility.pre_speech_padding_ms, 400
        )
    return cfg
