"""
YAHA Parser Engine v2

This package contains the deterministic parser pipeline used to:
- Classify user messages into containers (food / sleep / exercise / unknown)
- Shape and validate JSON according to the YAHA Parser Contract v2.

Nothing in this package should talk directly to Flask, Telegram, or Supabase.
It is pure logic.
"""

from .contract import ParserOutput, CONTAINERS

__all__ = [
    "ParserOutput",
    "CONTAINERS",
]

