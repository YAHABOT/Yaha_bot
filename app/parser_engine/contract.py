from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Literal, TypedDict

# Allowed containers in v2
CONTAINERS = ("food", "sleep", "exercise", "unknown")


class ParserOutputDict(TypedDict):
    """
    The canonical JSON contract for Parser Engine v2.

    This must be the ONLY shape that leaves the parser.
    """
    container: Literal["food", "sleep", "exercise", "unknown"]
    data: Dict[str, Any]
    confidence: float
    issues: List[str]
    reply_text: str


@dataclass
class ParserOutput:
    """
    Python representation of the parser result.

    Use .to_dict() before sending to Telegram / Supabase / entries table.
    """
    container: str
    data: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    issues: List[str] = field(default_factory=list)
    reply_text: str = ""

    def __post_init__(self) -> None:
        # Normalise container
        if self.container not in CONTAINERS:
            self.issues.append(f"Invalid container: {self.container!r}, coerced to 'unknown'.")
            self.container = "unknown"

        # Clamp confidence to [0, 1]
        if not isinstance(self.confidence, (int, float)):
            self.issues.append("Confidence was not numeric, set to 0.0.")
            self.confidence = 0.0
        else:
            if self.confidence < 0.0:
                self.confidence = 0.0
            if self.confidence > 1.0:
                self.confidence = 1.0

        # Basic safety checks
        if not isinstance(self.data, dict):
            self.issues.append("Data payload was not an object, replaced with empty dict.")
            self.data = {}

        if not isinstance(self.reply_text, str):
            self.issues.append("reply_text was not a string, replaced with empty string.")
            self.reply_text = ""

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def to_dict(self) -> ParserOutputDict:
        """
        Return a plain dict matching ParserOutputDict / JSON contract.
        """
        d = asdict(self)
        # type narrowing for mypy / TypedDict
        return {
            "container": d["container"],
            "data": d["data"],
            "confidence": float(d["confidence"]),
            "issues": list(d["issues"]),
            "reply_text": d["reply_text"],
        }

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "ParserOutput":
        """
        Build from a raw GPT or ad-hoc dict, applying defensive defaults.
        """
        container = raw.get("container", "unknown")
        data = raw.get("data") or {}
        confidence = raw.get("confidence", 0.0)
        issues = raw.get("issues") or []
        reply_text = raw.get("reply_text", "")

        # Coerce obvious types
        if not isinstance(issues, list):
            issues = [str(issues)]

        return cls(
            container=str(container),
            data=data if isinstance(data, dict) else {},
            confidence=float(confidence) if isinstance(confidence, (int, float, str)) else 0.0,
            issues=[str(i) for i in issues],
            reply_text=str(reply_text),
        )

    @classmethod
    def unknown(
        cls,
        raw_text: str,
        reason: str = "Could not classify as food, sleep, or exercise.",
    ) -> "ParserOutput":
        """
        Convenience constructor when we can't classify input.
        """
        return cls(
            container="unknown",
            data={"raw_text": raw_text},
            confidence=0.0,
            issues=[reason],
            reply_text="⚠️ I couldn't classify that as food, sleep, or exercise. Try being a bit more specific.",
        )

