"""
OCR module (Image → Text)

Build 019.2:
- Mock OCR implementation.
- Deterministic output for testing.
- Real OCR added in Build 019.5.
"""

from typing import Optional


def perform_ocr(image_bytes: bytes, fail: bool = False) -> Optional[str]:
    """
    Mock OCR for Build 019.2.

    Args:
        image_bytes (bytes): Raw image bytes (unused in mock).
        fail (bool): If True → simulate OCR failure.

    Returns:
        Optional[str]: Simulated extracted text.
    """

    if fail:
        return None

    # Deterministic mock text (pretend OCR result)
    return (
        "Meal: Chicken rice bowl\n"
        "Calories: 620 kcal\n"
        "Protein: 42g\n"
        "Carbs: 55g\n"
        "Fat: 18g\n"
    )
