"""Tier 2 SLM intent router — natural-language fallback after Tier 1 regex grammar.

Uses llama-cpp-python (optional) to classify transcripts that the regex grammar
could not match. Disabled automatically when the library is missing or no model
file is configured.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from yazses.commands.grammar import CommandIntent, IntentType

if TYPE_CHECKING:
    # Only imported for type hints; real import is deferred to __init__.
    from llama_cpp import Llama  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE = """\
You are a voice command classifier. Classify the utterance as one of the known intents.
Return ONLY valid JSON on one line: {{"intent": "<name>", "action": "<action>", "args": {{}}, "confidence": <0.0-1.0>}}

Known intents: dictate, edit (actions: delete_words, delete_lines, undo, save, copy, paste, comment, select_lines, select_to_end, select_all, new_function, new_class, new_file), navigate (actions: go_to_line, go_to_function, go_to_class, go_to_file), refactor (actions: rename_symbol), terminal (actions: run_tests, run_build, run_last, run_command)

Examples:
"close this tab" -> {{"intent": "edit", "action": "save", "args": {{}}, "confidence": 0.5}}
"go to line forty two" -> {{"intent": "navigate", "action": "go_to_line", "args": {{"n": "42"}}, "confidence": 0.95}}
"run the tests please" -> {{"intent": "terminal", "action": "run_tests", "args": {{}}, "confidence": 0.92}}
"hello world" -> {{"intent": "dictate", "action": "inject", "args": {{}}, "confidence": 0.98}}

Utterance: "{transcript}"
Classification:"""

# ---------------------------------------------------------------------------
# Intent type mapping
# ---------------------------------------------------------------------------

_INTENT_MAP: dict[str, IntentType] = {
    "dictate": IntentType.DICTATE,
    "navigate": IntentType.NAVIGATE,
    "edit": IntentType.EDIT,
    "refactor": IntentType.REFACTOR,
    "terminal": IntentType.TERMINAL,
}


class SLMRouter:
    """Tier 2 intent classifier backed by a local GGUF language model.

    When disabled (missing library or invalid model path) every call to
    :meth:`classify` returns ``None`` so the caller falls back to the Tier 1
    regex result transparently.
    """

    def __init__(
        self,
        model_path: str,
        threshold: float = 0.75,
        extra_examples: list[str] | None = None,
    ) -> None:
        """Initialise the router.

        Parameters
        ----------
        model_path:
            Absolute or relative path to the GGUF model file.  An empty string
            or a path that does not exist on disk disables the router.
        threshold:
            Minimum confidence score (0–1) that the model must report for its
            classification to be accepted.  Responses below this value cause
            :meth:`classify` to return ``None``.
        extra_examples:
            Additional few-shot example lines (same format as the built-in
            examples) appended to the prompt. Produced by ``yazses tune`` and
            loaded from ``<data_dir>/few_shots.toml``; lets the corpus teach the
            router to stop misfiring on specific utterances.
        """
        self._enabled = False
        self._model: Llama | None = None
        self._threshold = threshold
        self._extra_examples = extra_examples or []

        if not model_path:
            logger.debug("SLMRouter disabled: model_path is empty")
            return

        if not Path(model_path).is_file():
            logger.warning("SLMRouter disabled: model file not found at %r", model_path)
            return

        try:
            from llama_cpp import Llama  # type: ignore[import-untyped]  # noqa: PLC0415
        except ImportError:
            logger.debug(
                "SLMRouter disabled: llama-cpp-python is not installed "
                "(install it with: pip install llama-cpp-python)"
            )
            return

        try:
            self._model = Llama(model_path=model_path, n_ctx=512, verbose=False)
            self._enabled = True
            logger.info("SLMRouter loaded model from %r (threshold=%.2f)", model_path, threshold)
        except Exception:
            logger.exception("SLMRouter disabled: failed to load model from %r", model_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Whether the router has a working model and will attempt inference."""
        return self._enabled

    def classify(self, transcript: str, profile: str = "default") -> CommandIntent | None:
        """Attempt to classify *transcript* using the local SLM.

        Parameters
        ----------
        transcript:
            Raw transcribed text that Tier 1 returned as ``DICTATE``.
        profile:
            Editor profile name (passed through for future per-profile
            prompt specialisation; not yet used).

        Returns
        -------
        CommandIntent or None
            ``None`` signals the caller to treat the utterance as plain
            dictation — either because the router is disabled, confidence is
            below threshold, the model output could not be parsed, or the
            model itself classified the text as ``dictate``.
        """
        if not self._enabled or self._model is None:
            return None

        try:
            return self._run_inference(transcript, profile)
        except Exception:
            logger.exception("SLMRouter.classify raised unexpectedly — returning None")
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, transcript: str) -> str:
        # Escape any embedded quotes so the model receives well-formed text.
        safe = transcript.replace('"', '\\"')
        prompt = _PROMPT_TEMPLATE.format(transcript=safe)
        if self._extra_examples:
            extra = "\n".join(self._extra_examples) + "\n"
            # Insert learned examples right before the utterance under test.
            prompt = prompt.replace("Utterance:", extra + "Utterance:", 1)
        return prompt

    def _run_inference(self, transcript: str, profile: str) -> CommandIntent | None:  # noqa: ARG002
        assert self._model is not None  # satisfied by enabled guard in classify()

        prompt = self._build_prompt(transcript)

        result: Any = self._model.create_completion(
            prompt,
            max_tokens=100,
            temperature=0.0,
            stop=["\n"],
        )

        # llama-cpp-python returns a dict with a 'choices' list.
        try:
            raw_text: str = result["choices"][0]["text"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            logger.debug("SLMRouter: unexpected completion structure (%s): %r", exc, result)
            return None

        logger.debug("SLMRouter raw output: %r", raw_text)

        return self._parse_response(raw_text, transcript)

    def _parse_response(self, raw_text: str, original_transcript: str) -> CommandIntent | None:
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            logger.debug("SLMRouter: JSON parse error (%s) for response %r", exc, raw_text)
            return None

        if not isinstance(data, dict):
            logger.debug("SLMRouter: response is not a JSON object: %r", raw_text)
            return None

        intent_str = data.get("intent", "")
        action = data.get("action", "")
        args = data.get("args", {})
        confidence = data.get("confidence", 0.0)

        # Validate types to guard against malformed model output.
        if not isinstance(intent_str, str) or not isinstance(action, str):
            logger.debug("SLMRouter: intent or action field is not a string: %r", data)
            return None

        if not isinstance(args, dict):
            logger.debug("SLMRouter: args field is not a dict: %r", data)
            args = {}

        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            logger.debug("SLMRouter: invalid confidence value: %r", data.get("confidence"))
            return None

        # Normalise args values to str so CommandIntent's type contract holds.
        str_args: dict[str, str] = {str(k): str(v) for k, v in args.items()}

        intent_type = _INTENT_MAP.get(intent_str.lower())
        if intent_type is None:
            logger.debug("SLMRouter: unknown intent %r — treating as unclassified", intent_str)
            return None

        # DICTATE means the model thinks this is plain text; signal the caller
        # to inject it as-is rather than returning a CommandIntent.
        if intent_type is IntentType.DICTATE:
            logger.debug("SLMRouter: model classified as DICTATE — returning None")
            return None

        if confidence < self._threshold:
            logger.debug(
                "SLMRouter: confidence %.3f below threshold %.3f for intent %r — returning None",
                confidence,
                self._threshold,
                intent_str,
            )
            return None

        return CommandIntent(
            intent=intent_type,
            action=action,
            args=str_args,
            raw_text=original_transcript,
        )
