"""Polyglot Switch — code-switched transcription (design/v2-cognitive-layer §3.4).

P0 (here): the LID routing scaffolding for one configured language pair. The
CS-adapted model needs training (stock Whisper cannot code-switch) and is gated;
this plumbing slots it in once trained.
"""
