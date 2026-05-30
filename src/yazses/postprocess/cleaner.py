import re

_BLANK_ARTEFACTS = {"[BLANK_AUDIO]", "(blank)", "[INAUDIBLE]", "[silence]"}


def clean_text(text: str) -> str:
    text = text.strip()
    if text in _BLANK_ARTEFACTS:
        return ""
    text = re.sub(r"^[\s.…]+", "", text)
    return text.strip()
