"""Deterministic clean-up of customer text before any model sees it (D7a, layer 2)."""

import re
import unicodedata
from dataclasses import dataclass

MAX_CHARS = 2000
# Zero-width and bidirectional-override characters, word joiners and the byte-order mark.
INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤﻿]")


@dataclass(frozen=True)
class Sanitized:
    text: str
    truncated: bool


def sanitize(text: str) -> Sanitized:
    """NFKC, no control or invisible characters (newlines stay), collapsed whitespace, and a
    cap of MAX_CHARS characters."""
    text = unicodedata.normalize("NFKC", text)
    text = INVISIBLE.sub("", text)
    text = "".join(char for char in text if char in "\n\t" or unicodedata.category(char) != "Cc")
    lines = (" ".join(line.split()) for line in text.split("\n"))
    text = "\n".join(line for line in lines if line)
    if len(text) > MAX_CHARS:
        return Sanitized(text=text[:MAX_CHARS], truncated=True)
    return Sanitized(text=text, truncated=False)
