import logging

import numpy as np
from faster_whisper import WhisperModel

log = logging.getLogger(__name__)


class FasterWhisperEngine:
    def __init__(
        self,
        model_name: str = "tiny.en",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        log.info("Loading STT model '%s' on %s (%s)...", model_name, device, compute_type)
        self._model = WhisperModel(model_name, device=device, compute_type=compute_type)
        log.info("Model loaded.")

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        initial_prompt: str | None = None,
    ) -> str:
        if audio.size == 0:
            return ""
        kwargs: dict = {"language": "en"}
        if initial_prompt:
            kwargs["initial_prompt"] = initial_prompt
        segments, _ = self._model.transcribe(audio, **kwargs)
        return " ".join(seg.text.strip() for seg in segments).strip()
