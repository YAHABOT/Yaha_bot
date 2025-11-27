"""
File parser for text-based documents (TXT, CSV, simple PDFs)

Build 019.1:
- Only signatures + docstrings.
"""

from typing import Optional


def parse_file(file_bytes: bytes, filename: str) -> Optional[str]:
    """
    Extract text from a document.

    Build 019.1: Stub only.

    Returns:
        Optional[str]: Extracted text or None.
    """
    raise NotImplementedError("parse_file() will be implemented in Build 019.5.")
