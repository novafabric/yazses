"""Cross-platform daemon orchestrator.

Wires the hotkey backend → audio recorder → STT engine → injector pipeline,
exposes a JSON-RPC IPC server for the CLI and tray, and manages PID/signal
lifecycle. All platform-specific concerns are reached through
:mod:`yazses.platform`.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping

import numpy as np
from dataclasses import dataclass
from types import FrameType

from yazses.audio.padding import PreSpeechRingBuffer
from yazses.audio.recorder import AudioRecorder
from yazses.audio.vad_calibrated import is_silent_calibrated
from yazses.commands.dispatch import dispatch as cmd_dispatch
from yazses.commands.grammar import IntentType, classify
from yazses.commands.macros import MacroContext, build_macro_table
from yazses.commands.revise import DictationLedger, parse_revise
from yazses.config import Config, load_config
from yazses.inject.streaming import StreamingInjector
from yazses.ipc.protocol import Request
from yazses.learning.capture import CorpusWriter, build_writer
from yazses.platform import Platform, get_platform
from yazses.platform.base import HotkeyBackend, InjectorBackend, IpcServer, TrayState
from yazses.postprocess.cleaner import clean_text
from yazses.postprocess.llm_cleanup import LlmCleaner, build_cleaner
from yazses.postprocess.prosody import Word, annotate
from yazses.postprocess.punch_in import apply_top_candidate
from yazses.postprocess.spacing import continuation_prefix
from yazses.remote.forwarder import RemoteForwarder
from yazses.remote.local_proxy import RemoteInjectorProxy
from yazses.stt.endpoint import EndpointAnticipator
from yazses.stt.faster_whisper import FasterWhisperEngine
from yazses.stt.filters.disfluency import filter_transcript
from yazses.stt.streaming import StreamingEngine

log = logging.getLogger(__name__)


def should_launch_overlay(config: Config, env: Mapping[str, str]) -> bool:
    """Whether the daemon should auto-spawn the voice-activity overlay.

    Only when explicitly enabled in config AND a graphical session is present
    (``DISPLAY`` for X11 or ``WAYLAND_DISPLAY``). Headless servers and the test
    suite therefore never spawn it.
    """
    if not config.overlay.enabled:
        return False
    return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


@dataclass
class _DaemonState:
    state: TrayState = TrayState.LOADING
    last_error: str | None = None
    started_at: float = 0.0
    ready: bool = False
    # Live mic level (mean(|samples|)) of the most recent audio chunk while
    # recording; 0.0 otherwise. Surfaced over `status` to drive the overlay.
    audio_level: float = 0.0


class Daemon:
    """The dictation daemon. Holds a hotkey listener and an IPC server."""

    def __init__(
        self,
        config: Config | None = None,
        platform: Platform | None = None,
    ) -> None:
        self._config = config or load_config()
        self._platform = platform or get_platform()
        self._state = _DaemonState()
        self._lock = threading.RLock()
        self._hotkey: HotkeyBackend | None = None
        self._injector: InjectorBackend | None = None
        self._engine: FasterWhisperEngine | None = None
        self._recorder: AudioRecorder | None = None
        self._ipc_server: IpcServer | None = None
        self._padding_buffer: PreSpeechRingBuffer | None = None
        self._remote_forwarder: RemoteForwarder | None = None
        self._remote_injector: RemoteInjectorProxy | None = None
        self._stream_engine: StreamingEngine | None = None
        self._stream_injector: StreamingInjector | None = None
        # Ghost Ahead endpoint anticipator (None when [endpoint] disabled — dormant).
        self._endpoint: EndpointAnticipator | None = (
            EndpointAnticipator(
                min_silence_s=self._config.endpoint.min_silence_s,
                stable_updates=self._config.endpoint.stable_updates,
                debounce_s=self._config.endpoint.debounce_ms / 1000.0,
            )
            if self._config.endpoint.enabled
            else None
        )
        self._poll_stop: threading.Event | None = None
        self._poll_thread: threading.Thread | None = None
        # monotonic timestamp of the last dictation injection; drives
        # continuation spacing between successive hold-to-talk bursts.
        self._last_dictation_monotonic: float | None = None
        self._streaming_active: bool = False
        self._corpus: CorpusWriter | None = None
        self._edit_watcher = None
        self._cleaner: LlmCleaner | None = None
        self._overlay_proc: subprocess.Popen | None = None
        # Say-Macro table (None when [macros] disabled — feature dormant).
        self._macro_table = build_macro_table(
            self._config, self._platform.paths.config_file.parent
        )
        # Mid-Thought Undo: ledger of injected dictation bursts for "scratch that".
        self._ledger = DictationLedger()

    # ---- Public entrypoints -----------------------------------------------

    def run(self) -> None:
        self._configure_logging()
        self._install_signal_handlers()

        lifecycle = self._platform.lifecycle
        lifecycle.write_pid()
        with self._lock:
            self._state.started_at = time.monotonic()
            self._state.state = TrayState.LOADING
        try:
            # Start IPC FIRST so the tray and CLI see honest state immediately,
            # rather than getting "daemon not reachable" for the 5–10 seconds
            # the model takes to load on first run.
            self._start_ipc_server()
            self._build_pipeline()
            with self._lock:
                self._state.ready = True
                self._state.state = TrayState.IDLE
            assert self._hotkey is not None
            log.info("YazSes ready. Hold %s to dictate.", self._resolved_hotkey())
            self._maybe_launch_overlay()
            self._hotkey.run()
        finally:
            self._shutdown()

    def _maybe_launch_overlay(self) -> None:
        """Spawn the sonar overlay as a detached process when configured."""
        if not should_launch_overlay(self._config, os.environ):
            return
        try:
            self._overlay_proc = subprocess.Popen(
                [sys.executable, "-m", "yazses.overlay.app"],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info("Launched voice-activity overlay (pid %d).", self._overlay_proc.pid)
        except Exception:
            log.exception("Failed to launch overlay; continuing without it")

    def shutdown(self) -> None:
        log.info("Shutting down.")
        if self._hotkey is not None:
            try:
                self._hotkey.stop()
            except Exception:
                log.exception("Hotkey stop raised")
        # The rest happens in the finally block of run().

    # ---- Build phase -------------------------------------------------------

    def _build_pipeline(self) -> None:
        cfg = self._config
        log.info("Loading STT model %r...", cfg.stt.model)
        self._engine = FasterWhisperEngine(
            model_name=cfg.stt.model,
            device=cfg.stt.device,
            compute_type=cfg.stt.compute_type,
        )

        self._injector = self._platform.injector_factory()
        log.info("Injection backend: %s", type(self._injector).__name__)

        if cfg.streaming.enabled:
            self._stream_engine = StreamingEngine(
                self._engine._model,
                cfg.streaming.partial_interval_ms,
            )
            log.info("Streaming STT enabled (partial every %d ms)", cfg.streaming.partial_interval_ms)

        if self._endpoint is not None:
            log.info("Endpoint anticipation enabled (pre-warm=%s)", cfg.endpoint.prewarm)

        self._recorder = AudioRecorder(
            cfg.audio.sample_rate,
            cfg.audio.max_record_seconds,
            on_chunk=self._on_audio_chunk,
        )

        self._padding_buffer = PreSpeechRingBuffer(
            padding_ms=cfg.accessibility.pre_speech_padding_ms,
            sample_rate=cfg.audio.sample_rate,
        )

        key_id = cfg.hotkey.key
        if key_id == "auto":
            key_id = self._platform.default_hotkey
        self._hotkey = self._platform.hotkey_factory(
            key_id,
            cfg.hotkey.hold_threshold_ms,
            self._on_hold_start,
            self._on_hold_end,
        )

        # Opt-in self-improvement corpus (ADR-012). Dormant unless enabled.
        self._corpus = build_writer(self._platform.paths.data_dir, cfg.learning)

        # Opt-in post-dictation edit capture (signal b). Reads the editor line
        # back after a dictation; never logs keystrokes. Disabled unless a
        # reachable editor socket is configured.
        self._edit_watcher = None
        if self._corpus is not None and cfg.learning.capture_edits:
            from yazses.learning.edit_watch import EditWatcher, build_neovim_reader

            reader = build_neovim_reader(cfg.learning.editor_socket)
            if reader is not None:
                self._edit_watcher = EditWatcher(
                    reader,
                    self._corpus.update_correction_for,
                    delay_s=cfg.learning.edit_capture_delay_s,
                )
                log.info("Edit capture enabled (editor read-back).")

        # Opt-in offline LLM dictation cleanup (parity with Rust [cleanup]).
        # None unless [filters.disfluency] llm_enabled is set.
        self._cleaner = build_cleaner(cfg.filters.disfluency)

    def _start_ipc_server(self) -> None:
        socket_path = self._platform.paths.ipc_socket
        server = self._platform.ipc_server_factory(socket_path)
        server.register("status", self._handle_status)
        server.register("shutdown", self._handle_shutdown)
        server.register("inject", self._handle_inject)
        server.register("remote_start", self._handle_remote_start)
        server.register("remote_stop", self._handle_remote_stop)
        server.register("remote_status", self._handle_remote_status)
        server.register("enroll_start", self._handle_enroll_start)
        server.register("streaming_enable", self._handle_streaming_enable)
        server.register("streaming_disable", self._handle_streaming_disable)
        server.register("mark_last_wrong", self._handle_mark_last_wrong)
        server.register("punch_in", self._handle_punch_in)
        server.serve_in_thread()
        self._ipc_server = server

    # ---- Pipeline callbacks -----------------------------------------------

    def _on_hold_start(self, leaked: int) -> None:
        with self._lock:
            self._state.state = TrayState.RECORDING
        log.info("Recording started (cleaning up %d leaked char(s))", leaked)
        if leaked > 0 and self._injector is not None:
            try:
                self._injector.inject_backspaces(leaked)
            except Exception as exc:
                log.warning("Failed to clean %d leaked char(s): %s", leaked, exc)

        if self._stream_engine is not None and self._config.streaming.enabled:
            self._stream_engine.start()
            # Seed with pre-speech padding so voice onset isn't lost
            if self._padding_buffer is not None:
                padding = self._padding_buffer.get()
                if padding.size > 0:
                    self._stream_engine.push(padding)
            self._stream_injector = StreamingInjector(self._active_injector())
            self._poll_stop = threading.Event()
            stop = self._poll_stop
            self._poll_thread = threading.Thread(
                target=self._partial_poll_loop,
                args=(stop,),
                daemon=True,
                name="partial-poll",
            )
            self._streaming_active = True
            self._poll_thread.start()

        if self._recorder is not None:
            try:
                self._recorder.start()
            except Exception as exc:
                log.error("Microphone unavailable: %s", exc)
                self._streaming_active = False
                if self._poll_stop is not None:
                    self._poll_stop.set()
                with self._lock:
                    self._state.last_error = f"Microphone unavailable: {exc}"
                    self._state.state = TrayState.IDLE

    def _on_hold_end(self) -> None:
        log.info("Recording stopped, transcribing...")

        # Stop streaming poll before touching the injector state
        self._streaming_active = False
        if self._poll_stop is not None:
            self._poll_stop.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=1.0)
            self._poll_thread = None

        if self._recorder is None or self._engine is None or self._injector is None:
            return
        with self._lock:
            self._state.state = TrayState.TRANSCRIBING

        stream_injector = self._stream_injector
        self._stream_injector = None

        # Learning corpus event accumulated across the pipeline; written once in
        # the finally block when capture is enabled. None-safe and never blocking.
        event: dict = {"ts": time.time(), "model": self._config.stt.model}
        clip: np.ndarray | None = None
        sample_rate = self._config.audio.sample_rate

        try:
            audio = self._recorder.stop()

            # Accumulate in ring buffer; build padded audio for VAD
            if self._padding_buffer is not None:
                self._padding_buffer.push(audio)
                padded = self._padding_buffer.prepend_padding(audio)
            else:
                padded = audio

            clip = padded
            event["audio_secs"] = padded.size / sample_rate
            event["level"] = float(np.abs(padded).mean()) if padded.size else 0.0

            # VAD
            if is_silent_calibrated(padded, self._config.accessibility):
                event["discard_reason"] = "silent"
                level = float(np.abs(padded).mean()) if padded.size else 0.0
                log.info(
                    "Silent audio -- discarding (level %.4f < vad_threshold %.4f; "
                    "run 'yazses mic-level --set' to retune).",
                    level,
                    self._config.accessibility.vad_threshold,
                )
                if stream_injector is not None:
                    stream_injector.cancel()
                return

            use_streaming = (
                self._config.streaming.enabled
                and self._stream_engine is not None
                and stream_injector is not None
            )

            audio_secs = padded.size / self._config.audio.sample_rate
            # Prosody Ink (batch only) needs per-word timestamps; capture them on
            # the non-streaming path when [prosody] enabled, else use the fast
            # path so non-prosody users never pay the word_timestamps cost.
            prosody_words: list[Word] = []
            want_prosody = self._config.prosody.enabled and not use_streaming
            t_decode = time.monotonic()
            if use_streaming:
                assert self._stream_engine is not None
                text = self._stream_engine.commit()
            elif want_prosody:
                text, prosody_words = self._engine.transcribe_words(
                    padded,
                    self._config.audio.sample_rate,
                    initial_prompt=self._config.stt.initial_prompt or None,
                )
            else:
                text = self._engine.transcribe(
                    padded,
                    self._config.audio.sample_rate,
                    initial_prompt=self._config.stt.initial_prompt or None,
                )
            decode_ms = (time.monotonic() - t_decode) * 1000.0
            event["raw_text"] = text
            event["decode_ms"] = decode_ms
            # Metadata only (no transcript text) so the file log is safe to share.
            log.info(
                "Transcribed %.1fs audio in %.0f ms (model %s, level %.4f)",
                audio_secs, decode_ms, self._config.stt.model,
                float(np.abs(padded).mean()) if padded.size else 0.0,
            )

            text = clean_text(text)
            event["cleaned_text"] = text
            if not text:
                event["discard_reason"] = "empty"
                log.info("Empty transcription -- discarding.")
                if stream_injector is not None:
                    stream_injector.cancel()
                return

            if self._config.filters.disfluency.enabled:
                result = filter_transcript(text, self._config.filters.disfluency)
                text = result.text
                event["filtered_text"] = text
                if not text:
                    event["discard_reason"] = "post_filter"
                    log.info("Post-filter empty -- discarding.")
                    if stream_injector is not None:
                        stream_injector.cancel()
                    return

            # INFO: metadata only (length); DEBUG: the actual text.
            log.info("Injecting %d chars, %d words.", len(text), len(text.split()))
            log.debug("Injecting text: %r", text)
            with self._lock:
                self._state.state = TrayState.INJECTING

            injector = self._active_injector()
            event["final_text"] = text
            event["injected"] = True

            # Classify first so we know whether this burst is dictation (which
            # gets cleanup + continuation spacing) or a command (key sequence —
            # no spacing, no dictation-timestamp update).
            intent = None
            if self._config.commands.enabled:
                intent = classify(text, self._config.commands.profile,
                                   macro_table=self._macro_table)
                event["intent_type"] = intent.intent.value
                event["intent_action"] = intent.action
            is_dictation = intent is None or intent.intent == IntentType.DICTATE

            # Mid-Thought Undo: a whole-utterance "scratch that" deletes the last
            # burst YazSes injected (backspaces), instead of typing it literally.
            if is_dictation and self._config.revise.enabled and parse_revise(text):
                if use_streaming and stream_injector is not None:
                    stream_injector.cancel()
                n = self._ledger.scratch_last()
                if n > 0:
                    injector.inject_key_sequence(["BackSpace"] * n)
                event["intent_type"] = "revise"
                event["revise_chars"] = n
                log.info("Mid-thought undo: scratched %d chars.", n)
                return

            if is_dictation:
                text = self._clean_dictation(text, event)
                # Prosody Ink: map vocal prosody (inter-word pause, emphasis) onto
                # text formatting. Batch + dictation only; word timings drive the
                # spacing/emphasis, content stays the cleaned text. Off by default.
                if want_prosody and prosody_words:
                    presult = annotate(
                        text, padded, sample_rate, prosody_words, self._config.prosody
                    )
                    if presult.latency_ms > self._config.prosody.max_latency_ms:
                        log.warning(
                            "Prosody pass took %.0f ms (> max_latency_ms %d); "
                            "consider format=none (pause-only).",
                            presult.latency_ms, self._config.prosody.max_latency_ms,
                        )
                    text = presult.text
                    event["prosody_breaks"] = presult.paragraph_breaks
                    event["prosody_emphasized"] = presult.emphasized
                    event["final_text"] = text
                # Prepend a separating space when this dictation continues a
                # recent burst, so consecutive hold-to-talk utterances don't
                # glue together at the boundary ("words together" + "I mean"
                # -> "... togetherI mean"). Suppressed before closing punctuation.
                if self._config.injection.continuation_window_ms > 0:
                    window_s = self._config.injection.continuation_window_ms / 1000.0
                    had_recent = (
                        self._last_dictation_monotonic is not None
                        and (time.monotonic() - self._last_dictation_monotonic) <= window_s
                    )
                    text = continuation_prefix(text, had_recent_injection=had_recent) + text
                event["final_text"] = text

            if not is_dictation:
                assert intent is not None
                if use_streaming and stream_injector is not None:
                    stream_injector.cancel()
                cmd_dispatch(intent, injector,
                             macro_table=self._macro_table,
                             macro_context=self._build_macro_context())
            else:
                if use_streaming:
                    assert stream_injector is not None
                    stream_injector.commit(text)
                else:
                    injector.inject(text)
                self._last_dictation_monotonic = time.monotonic()
                if self._config.revise.enabled:
                    self._ledger.record(text)

        except Exception as exc:
            log.warning("Pipeline error: %s", exc)
            with self._lock:
                self._state.last_error = str(exc)
            if stream_injector is not None:
                try:
                    stream_injector.cancel()
                except Exception:
                    pass
        finally:
            if self._corpus is not None and (
                event.get("raw_text") or event.get("discard_reason")
            ):
                cap_audio = clip if self._config.learning.capture_audio else None
                self._corpus.write(event, cap_audio, sample_rate)
            # Edit capture (signal b): for plain dictation, read the editor back
            # shortly and record any in-place correction.
            if (
                self._edit_watcher is not None
                and event.get("injected")
                and event.get("final_text")
                and event.get("intent_type", "dictate") == "dictate"
            ):
                self._edit_watcher.watch(event["final_text"])
            with self._lock:
                self._state.audio_level = 0.0  # recording done — overlay calms down
                if self._state.state in (TrayState.TRANSCRIBING, TrayState.INJECTING):
                    self._state.state = TrayState.IDLE

    def _on_audio_chunk(self, chunk: np.ndarray) -> None:
        """Called from the sounddevice audio thread for each recorded chunk."""
        # Publish the live mic level for the overlay. Same metric as the VAD
        # gate (mean(|samples|), cf. _on_hold_end / system.miclevel), kept cheap
        # because this runs on the audio callback thread.
        if chunk.size:
            with self._lock:
                self._state.audio_level = float(np.abs(chunk).mean())
        if self._streaming_active and self._stream_engine is not None:
            self._stream_engine.push(chunk)

    def _partial_poll_loop(self, stop: threading.Event) -> None:
        """Background thread: drain partial hypotheses and inject them."""
        while not stop.is_set():
            partial = self._stream_engine.get_partial() if self._stream_engine else None
            if partial and partial.text and self._stream_injector is not None:
                log.debug("Streaming partial: %r", partial.text)
                try:
                    self._stream_injector.inject_partial(partial.text)
                except Exception as exc:
                    log.warning("Partial inject error: %s", exc)
            # Ghost Ahead: feed the confirmed-prefix stability to the anticipator so
            # a likely endpoint pre-warms the decode path. Harmless; the real commit
            # still happens on hold-release.
            if self._endpoint is not None and self._stream_engine is not None:
                silence_s = self._stream_engine.prefix_stable_for_ms() / 1000.0
                self._endpoint_prewarm_tick(self._stream_engine._last_emitted, silence_s)
            stop.wait(timeout=0.05)

    def _endpoint_prewarm_tick(
        self, partial_text: str, silence_s: float, now: float | None = None
    ) -> bool:
        """Observe the endpoint signal; pre-warm the decode path on a likely stop.

        Returns whether an endpoint fired. No-op (returns False) when [endpoint] is
        disabled. Pre-warm is harmless — it eagerly decodes the streaming buffer and
        discards the result; the authoritative transcript is unchanged.
        """
        if self._endpoint is None:
            return False
        if now is None:
            now = time.monotonic()
        fired = self._endpoint.observe(partial_text, silence_s, now=now)
        if (
            fired
            and self._config.endpoint.prewarm
            and self._stream_engine is not None
        ):
            try:
                self._stream_engine.prewarm()
            except Exception as exc:
                log.debug("Endpoint pre-warm failed: %s", exc)
        return fired

    def _clean_dictation(self, text: str, event: dict) -> str:
        """Apply optional LLM cleanup to dictation text; record it in *event*.

        Returns *text* unchanged when cleanup is dormant or its guards reject the
        reformatted output. Never raises — :meth:`LlmCleaner.cleanup` swallows
        backend errors internally.
        """
        if self._cleaner is None:
            return text
        cleaned = self._cleaner.cleanup(text)
        if cleaned != text:
            event["llm_cleaned_text"] = cleaned
            event["final_text"] = cleaned
        return cleaned

    def _record_respeak(self) -> str:
        """Record a short window and transcribe it — the respoken Punch-In phrase.

        Bounded by ``[punch_in] record_seconds``. Reuses the daemon's own recorder
        and STT engine; returns the cleaned transcript ("" if nothing usable).
        """
        if self._recorder is None or self._engine is None:
            return ""
        self._recorder.start()
        window = max(0.0, self._config.punch_in.record_seconds)
        if window:
            time.sleep(window)
        audio = self._recorder.stop()
        if audio.size == 0:
            return ""
        text = self._engine.transcribe(audio, self._config.audio.sample_rate)
        return clean_text(text)

    def _handle_punch_in(self, request: Request) -> dict[str, object]:
        """IPC: re-record a phrase and correct the last dictation burst (spec-punch-in)."""
        if not self._config.punch_in.enabled:
            return {"ok": False, "reason": "punch_in disabled in config"}
        with self._lock:
            ready = self._state.ready
        if not ready:
            return {"ok": False, "reason": "daemon still loading; try again in a moment"}
        if not self._ledger.last_text():
            return {"ok": False, "reason": "nothing to correct"}
        respoken = str(request.params.get("respoken", "")) or self._record_respeak()
        if not respoken:
            return {"ok": False, "reason": "no respoken phrase captured"}
        choose = int(request.params.get("choose", 0))
        apply = bool(request.params.get("apply", True))
        return self._apply_punch_in(respoken, choose=choose, apply=apply)

    def _apply_punch_in(
        self, respoken: str, choose: int = 0, apply: bool = True
    ) -> dict[str, object]:
        """Correct the last dictation burst by re-speaking part of it (spec-punch-in).

        Aligns ``respoken`` against the last YazSes-injected burst, deletes that
        burst (backspaces — works in any text field), retypes the corrected text,
        and updates the ledger so a later "scratch that" still works. Returns a
        result dict with ``ok``, ``old``/``new`` text, and the ranked ``candidates``
        so the caller (CLI) can let the user confirm or pick a different span. With
        ``apply=False`` it is a dry run: candidates and the proposed ``new`` text are
        returned but nothing is injected. Never edits when there is no history or
        nothing clears the similarity threshold.
        """
        last = self._ledger.last_text()
        if not last:
            return {"ok": False, "reason": "nothing to correct", "candidates": []}
        corrected, cands = apply_top_candidate(
            last,
            respoken,
            max_candidates=self._config.punch_in.max_candidates,
            min_score=self._config.punch_in.min_score,
            choose=choose,
        )
        cand_view = [
            {"old": c.old_text, "new": c.new_text, "score": round(c.score, 3)}
            for c in cands
        ]
        if corrected is None:
            return {"ok": False, "reason": "no confident match", "candidates": cand_view}
        if not apply:
            return {
                "ok": False, "applied": False, "old": last, "new": corrected,
                "candidates": cand_view,
            }
        injector = self._active_injector()
        injector.inject_backspaces(len(last))
        injector.inject(corrected)
        self._ledger.replace_last(corrected)
        self._last_dictation_monotonic = time.monotonic()
        log.info("Punch-In: corrected %d chars.", len(last))
        return {"ok": True, "applied": True, "old": last, "new": corrected, "candidates": cand_view}

    def _active_injector(self) -> InjectorBackend:
        """Return remote injector when remote session is active, else local."""
        with self._lock:
            remote_active = self._state.state == TrayState.REMOTE_ACTIVE
        if remote_active and self._remote_injector is not None:
            return self._remote_injector
        assert self._injector is not None
        return self._injector

    # ---- IPC handlers ------------------------------------------------------

    def _handle_status(self, _request: Request) -> dict[str, object]:
        with self._lock:
            uptime = (time.monotonic() - self._state.started_at) if self._state.started_at else 0.0
            return {
                "state": self._state.state.value,
                "model": self._config.stt.model,
                "hotkey": self._resolved_hotkey(),
                "injection_backend": type(self._injector).__name__ if self._injector else None,
                "last_error": self._state.last_error,
                "uptime_s": round(uptime, 2),
                "platform": self._platform.name,
                "streaming_enabled": self._config.streaming.enabled,
                "commands_enabled": self._config.commands.enabled,
                "remote_connected": self._remote_forwarder is not None and self._remote_forwarder.is_connected(),
                # For the voice-activity overlay (yazses-overlay).
                "audio_level": round(self._state.audio_level, 6),
                "vad_threshold": self._config.accessibility.vad_threshold,
            }

    def _handle_shutdown(self, _request: Request) -> dict[str, bool]:
        threading.Thread(target=self.shutdown, name="ipc-shutdown", daemon=True).start()
        return {"ok": True}

    def _handle_inject(self, request: Request) -> dict[str, object]:
        text = str(request.params.get("text", ""))
        if not text:
            return {"ok": False, "reason": "empty text"}
        with self._lock:
            ready = self._state.ready
        if not ready or self._injector is None:
            return {"ok": False, "reason": "daemon still loading; try again in a moment"}
        self._injector.inject(text)
        return {"ok": True, "backend": type(self._injector).__name__}

    def _handle_remote_start(self, request: Request) -> dict[str, object]:
        host = str(request.params.get("host", ""))
        if not host:
            return {"ok": False, "reason": "host is required"}
        port = int(request.params.get("port", self._config.remote.ssh_port))
        key_file = str(request.params.get("key_file", self._config.remote.key_file))

        with self._lock:
            self._state.state = TrayState.REMOTE_SETUP

        def _connect() -> None:
            try:
                fwd = RemoteForwarder(
                    agent_port=self._config.remote.agent_port,
                )
                fwd.connect(host=host, port=port, key_file=key_file)
                proxy = RemoteInjectorProxy(
                    host="127.0.0.1",
                    port=self._config.remote.agent_port,
                )
                with self._lock:
                    self._remote_forwarder = fwd
                    self._remote_injector = proxy
                    self._state.state = TrayState.REMOTE_ACTIVE
                log.info("Remote session active: %s", host)
            except Exception as exc:
                log.error("Remote connect failed: %s", exc)
                with self._lock:
                    self._state.state = TrayState.IDLE
                    self._state.last_error = str(exc)

        threading.Thread(target=_connect, name="remote-connect", daemon=True).start()
        return {"ok": True, "state": "connecting"}

    def _handle_remote_stop(self, _request: Request) -> dict[str, object]:
        with self._lock:
            fwd = self._remote_forwarder
            self._remote_forwarder = None
            self._remote_injector = None
            self._state.state = TrayState.IDLE
        if fwd is not None:
            try:
                fwd.disconnect()
            except Exception as exc:
                log.warning("Remote disconnect raised: %s", exc)
        return {"ok": True}

    def _handle_remote_status(self, _request: Request) -> dict[str, object]:
        with self._lock:
            connected = (
                self._remote_forwarder is not None
                and self._remote_forwarder.is_connected()
            )
            return {
                "connected": connected,
                "state": self._state.state.value,
            }

    def _handle_enroll_start(self, _request: Request) -> dict[str, object]:
        with self._lock:
            if self._state.state not in (TrayState.IDLE, TrayState.PAUSED):
                return {"ok": False, "reason": f"cannot enroll in state {self._state.state.value}"}
            self._state.state = TrayState.ENROLLING

        def _enroll() -> None:
            try:
                from yazses.accessibility.enroll import run_wizard
                run_wizard(config_path=self._platform.paths.config_file)
                # Reload config so the new thresholds take effect
                self._config = load_config(self._platform.paths.config_file)
                if self._padding_buffer is not None:
                    self._padding_buffer = PreSpeechRingBuffer(
                        padding_ms=self._config.accessibility.pre_speech_padding_ms,
                        sample_rate=self._config.audio.sample_rate,
                    )
            except Exception as exc:
                log.error("Enrollment error: %s", exc)
                with self._lock:
                    self._state.last_error = str(exc)
            finally:
                with self._lock:
                    if self._state.state == TrayState.ENROLLING:
                        self._state.state = TrayState.IDLE

        threading.Thread(target=_enroll, name="enroll", daemon=True).start()
        return {"ok": True, "state": "enrolling"}

    def _handle_streaming_enable(self, _request: Request) -> dict[str, object]:
        self._config.streaming.enabled = True
        if self._stream_engine is None and self._engine is not None:
            self._stream_engine = StreamingEngine(
                self._engine._model,
                self._config.streaming.partial_interval_ms,
            )
        return {"ok": True, "streaming_enabled": True}

    def _handle_streaming_disable(self, _request: Request) -> dict[str, object]:
        self._config.streaming.enabled = False
        return {"ok": True, "streaming_enabled": False}

    def _handle_mark_last_wrong(self, request: Request) -> dict[str, object]:
        if self._corpus is None:
            return {"ok": False, "reason": "learning capture is disabled"}
        params = request.params if isinstance(request.params, dict) else {}
        correction = params.get("correction")
        flagged = self._corpus.mark_last_wrong(correction)
        return {"ok": flagged}

    # ---- Signals & helpers -------------------------------------------------

    def _build_macro_context(self) -> MacroContext:
        """Resolve dynamic macro placeholders at injection time.

        date/time reflect the moment of dispatch. Clipboard capture is a P2
        item (left empty in P1), so ``${clipboard}`` resolves to "" for now.
        """
        from datetime import datetime
        now = datetime.now()
        return MacroContext(
            clipboard="",
            date=now.strftime("%Y-%m-%d"),
            time=now.strftime("%H:%M"),
            author=self._config.macros.author,
        )

    def _configure_logging(self) -> None:
        level_name = self._config.general.log_level.upper()
        level = logging.getLevelNamesMapping().get(level_name)
        if level is None:
            raise ValueError(f"Invalid log_level in config: {self._config.general.log_level!r}")
        fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
        logging.basicConfig(level=level, format=fmt)

        # Persist a rotating diagnostic log so `yazses start` (detached, stdout
        # to /dev/null) still leaves a record. Metadata only at INFO — the
        # transcript text is logged at DEBUG only, never in the default file.
        from logging.handlers import RotatingFileHandler

        log_dir = self._platform.paths.log_dir
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                log_dir / "daemon.log", maxBytes=1_000_000, backupCount=3
            )
            handler.setFormatter(logging.Formatter(fmt))
            handler.setLevel(level)
            logging.getLogger().addHandler(handler)
            log.info("Logging to %s", log_dir / "daemon.log")
        except OSError as exc:
            log.warning("Could not open log file in %s: %s", log_dir, exc)

    def _install_signal_handlers(self) -> None:
        def _cleanup(_signum: int, _frame: FrameType | None) -> None:
            self.shutdown()

        signal.signal(signal.SIGTERM, _cleanup)
        signal.signal(signal.SIGINT, _cleanup)

    def _resolved_hotkey(self) -> str:
        key = self._config.hotkey.key
        return self._platform.default_hotkey if key == "auto" else key

    def _shutdown(self) -> None:
        if self._overlay_proc is not None:
            try:
                self._overlay_proc.terminate()
            except Exception:
                log.exception("Overlay terminate raised")
        if self._edit_watcher is not None:
            try:
                self._edit_watcher.cancel()
            except Exception:
                log.exception("Edit watcher cancel raised")
        if self._corpus is not None:
            try:
                self._corpus.stop()
            except Exception:
                log.exception("Corpus writer stop raised")
        if self._remote_forwarder is not None:
            try:
                self._remote_forwarder.disconnect()
            except Exception:
                log.exception("Remote forwarder disconnect raised")
        if self._ipc_server is not None:
            try:
                self._ipc_server.shutdown()
            except Exception:
                log.exception("IPC server shutdown raised")
        try:
            self._platform.lifecycle.clear_pid()
        except Exception:
            log.exception("Lifecycle clear_pid raised")


def run() -> None:
    """Entry point used by `yazses-daemon` and `python -m yazses.main`."""
    try:
        Daemon().run()
    except KeyboardInterrupt:
        sys.exit(0)
