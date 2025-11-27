"""
Speech-to-text (Audio → Text)

Build 019.2:
- Mock STT implementation.
- Real STT added in Build 019.5.
"""

from typing import Optional


def perform_stt(audio_bytes: bytes, fail: bool = False) -> Optional[str]:
    """
    Mock speech-to-text for Build 019.2.

    Args:
        audio_bytes (bytes): Raw audio bytes (unused in mock).
        fail (bool): If True → simulate STT failure.

    Returns:
        Optional[str]: Simulated transcript.
    """

    if fail:
        return None

    return (
        "Breakfast was greek yogurt with honey and nuts. "
        "Around 380 calories, 24 grams protein, 40 carbs, 12 fat."
    )
