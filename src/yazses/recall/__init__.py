"""Spoken Recall & Ambient Scratch (ADR-v2-005).

Query past dictations from the encrypted learning corpus ("what did I say about
X") and capture spoken notes-to-self. Pure query/parse layers here; the daemon
adapts corpus records and owns the file-backed scratch pad. OFF by default —
gated by ``[recall]`` config.
"""
