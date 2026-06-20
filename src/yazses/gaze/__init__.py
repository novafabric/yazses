"""Glance-Type — look-to-pane gaze targeting (design/v2-cognitive-layer §3.3).

Coarse webcam gaze selects a screen zone/window so a hold-to-talk dictation lands
where you look. The gaze backend (L2CS-Net) lives in the optional ``gaze`` extra;
the calibration + zone mapping here are pure and dependency-free. Frames are used
in-RAM during a hold only — never stored or sent (ADR-011).
"""
