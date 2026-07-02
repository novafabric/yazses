"""Modality Role Router (ADR-v2-011).

Assign each available input modality its fastest role (voice→dictation,
EMG→command, gaze→targeting, keyboard→activate) and arbitrate when several claim
the same role. Pure policy — the EMG serial intake (``platform/emg``) and gaze
webcam intake stay opt-in and lazy; nothing here touches hardware. EXPERIMENTAL,
off by default.
"""
