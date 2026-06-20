"""Shared speaker voiceprint infrastructure (design/v2-cognitive-layer §2.1).

A one-time enrollment yields a speaker embedding (d-vector) reused by Cocktail
Filter (target-speaker gate) and Voiceprint Mind (personalization). The embedder
lives in the optional ``voiceprint`` extra; the embedding is biometric and is
stored only in the encrypted learning corpus (ADR-012).
"""
