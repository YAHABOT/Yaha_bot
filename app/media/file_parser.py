"""
File parser for text-based documents (TXT, CSV, simple PDFs)

Build 019.2:
- Mock file parsing implementation.
- Real parsing added in Build 019.5.
"""

from typing import Optional


def parse_file(file_bytes: bytes, filename: str, fail: bool = False) -> Optional[str]:
    """
    Mock file parser.

    Args:
        file_bytes (bytes): File content.
        filename (str): Original filename.
        fail (bool): Simulate parsing failure.

    Returns:
        Optional[str]: Mock extracted content.
    """

    if fail:
        return None

    # Example mock text based on filename
    if filename.lower().endswith(".csv"):
        return (
            "meal,calories,protein,carbs,fat\n"
            "salmon_poke,540,38,48,20"
        )

    if filename.lower().endswith(".txt"):
        return "Dinner: tofu stir fry 420 kcal protein 32g carbs 40g fat 12g"

    # Generic fallback
    return "Unknown document format but here is some sample extracted text."
