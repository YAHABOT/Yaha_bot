from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class MediaJob:
    """
    Internal representation of a media ingestion task.

    Build 019.1: Structure only. No logic.

    Fields:
        id: Unique internal job ID (string).
        chat_id: Chat identifier from the bot.
        user_id: Optional user id (if available).
        channel: "telegram", "whatsapp", "webapp".
        container: Optional container context ("food", "sleep", "exercise").
        media_type: "image", "audio", or "file".
        media_url: URL or storage path for raw media.
        status: "received", "extracted", "normalized", "failed".
        raw_text: Extracted text from OCR/STT/file.
        normalized_payload: Dict returned by the GPT fallback.
        error: Any error message if job fails.
    """

    id: str
    chat_id: str | int
    channel: str
    media_type: str
    media_url: str

    user_id: Optional[str | int] = None
    container: Optional[str] = None

    status: str = "received"
    raw_text: Optional[str] = None
    normalized_payload: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
