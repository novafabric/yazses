"""Tests for the offline disfluency filter."""
from __future__ import annotations
import json
import time
from pathlib import Path
import pytest
from yazses.config import DisfluencyConfig
from yazses.stt.filters.disfluency import filter_transcript, FilterResult

CORPUS_PATH = Path(__file__).parent / "fixtures" / "disfluency" / "corpus.json"


def load_corpus():
    with open(CORPUS_PATH) as f:
        return json.load(f)


@pytest.mark.parametrize("entry", load_corpus(), ids=lambda e: e["notes"][:40])
def test_corpus(entry):
    config = DisfluencyConfig()
    result = filter_transcript(entry["input"], config)
    assert result.text == entry["expected"], (
        f"Input: {entry['input']!r}\n"
        f"Expected: {entry['expected']!r}\n"
        f"Got: {result.text!r}"
    )


def test_runtime_under_10ms():
    config = DisfluencyConfig()
    text = "um so I uh need to basically uh you know delete last line uh right okay so"
    t0 = time.perf_counter()
    for _ in range(100):
        filter_transcript(text, config)
    elapsed_ms = (time.perf_counter() - t0) / 100 * 1000
    assert elapsed_ms < 10, f"filter_transcript took {elapsed_ms:.2f} ms (> 10 ms)"


def test_proper_nouns_unchanged():
    config = DisfluencyConfig()
    text = "Hello Python is great"
    result = filter_transcript(text, config)
    assert "Python" in result.text


def test_code_identifiers_unchanged():
    config = DisfluencyConfig()
    text = "call the function_name here"
    result = filter_transcript(text, config)
    assert "function_name" in result.text


def test_disabled_filter_passthrough():
    config = DisfluencyConfig(enabled=False)
    text = "um hello um world"
    result = filter_transcript(text, config)
    assert result.text == text
    assert result.chars_removed == 0


def test_chars_removed_counted():
    config = DisfluencyConfig()
    text = "um hello world"
    result = filter_transcript(text, config)
    assert result.chars_removed > 0


def test_empty_input():
    config = DisfluencyConfig()
    result = filter_transcript("", config)
    assert result.text == ""
    assert result.chars_removed == 0


def test_custom_filler_words():
    config = DisfluencyConfig(filler_words=["actually", "honestly"])
    text = "I actually honestly think this is good"
    result = filter_transcript(text, config)
    assert "actually" not in result.text
    assert "honestly" not in result.text
    assert "think this is good" in result.text
