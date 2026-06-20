"""Voiceprint Mind P1 — biasing prompt builder (design/v2-cognitive-layer §3.1).

Compose Whisper's ``initial_prompt`` from the user vocabulary + frequent personal
terms mined from the corpus, so the recognizer spells the user's jargon/proper nouns.
Pure, no training, no model — fully testable.
"""
from __future__ import annotations

from yazses.personalize.prompt_builder import build_prompt, mine_terms


# ---- build_prompt ----------------------------------------------------------

def test_build_prompt_unions_vocab_and_mined_terms():
    out = build_prompt(["Kubernetes", "kubectl"], ["GitHub"], existing_prompt="")
    for term in ("Kubernetes", "kubectl", "GitHub"):
        assert term in out


def test_build_prompt_preserves_existing_prompt():
    out = build_prompt(["Redis"], [], existing_prompt="Meeting notes.")
    assert "Meeting notes." in out
    assert "Redis" in out


def test_build_prompt_dedupes_case_insensitively():
    out = build_prompt(["GitHub", "github"], ["GitHub"], existing_prompt="")
    assert out.lower().count("github") == 1


def test_build_prompt_caps_term_count():
    terms = [f"Term{i}" for i in range(200)]
    out = build_prompt(terms, [], existing_prompt="", max_terms=10)
    assert sum(out.count(f"Term{i}") for i in range(200)) == 10


def test_build_prompt_empty_inputs_returns_existing():
    assert build_prompt([], [], existing_prompt="hello") == "hello"
    assert build_prompt([], [], existing_prompt="") == ""


# ---- mine_terms ------------------------------------------------------------

def test_mine_terms_returns_frequent_content_words():
    texts = [
        "deploy the kubernetes pod",
        "the kubernetes cluster is down",
        "restart kubernetes now",
    ]
    mined = mine_terms(texts, top_k=5, min_count=2)
    assert "kubernetes" in mined
    assert "the" not in mined  # stopword filtered


def test_mine_terms_ignores_rare_words():
    texts = ["a unique word here", "common common common"]
    mined = mine_terms(texts, top_k=5, min_count=2)
    assert "unique" not in mined
    assert "common" in mined


def test_mine_terms_empty_is_safe():
    assert mine_terms([], top_k=5) == []
