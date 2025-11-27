"""
Media ingestion pipeline.

Build 019.1:
- Contains NO logic.
- Defines the pipeline interface to be implemented in 019.3.
"""

from typing import Optional, Dict, Any
from app.media.models import MediaJob


def run_media_pipeline(job: MediaJob) -> MediaJob:
    """
    Master pipeline that processes a MediaJob end-to-end:

        raw media → extraction → GPT fallback → normalized dict

    Build 019.1:
        - Stub only
        - No OCR/STT/file parsing
        - No GPT fallback calls
        - No flow integrations

    Returns:
        MediaJob: Updated job (will be implemented in 019.3).
    """
    raise NotImplementedError("run_media_pipeline() will be implemented in Build 019.3.")
