"""
Media storage utilities.

Build 019.1:
- Only function signatures + docstrings.
- No real upload/download.
"""

from typing import Optional


def save_media_file(file_bytes: bytes, filename: str) -> str:
    """
    Save raw media to a storage backend (local or Supabase bucket).

    Build 019.1: Returns a placeholder path.
    
    Returns:
        str: A URL or local path where media is stored.
    """
    raise NotImplementedError("save_media_file() will be implemented in Build 019.4+")


def load_media_file(url: str) -> Optional[bytes]:
    """
    Load raw media bytes from storage.

    Build 019.1: Signature only.

    Returns:
        Optional[bytes]
    """
    raise NotImplementedError("load_media_file() will be implemented later.")
