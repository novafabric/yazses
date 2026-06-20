"""Voiceprint Mind — personalize STT to the user (design/v2-cognitive-layer §3.1).

P1 (here): bias the recognizer with personal context via ``initial_prompt`` — no
training, nearly free. P2 (later, gated): an opt-in nightly LoRA personal fine-tune.
"""
