"""Dutch is derived, never independently generated: one source of truth (the
frozen English entry), translated per entry, cached by hash of that English
text. If the English didn't move, no call is made and the Dutch can't move.
"""
from __future__ import annotations

import hashlib
import re

TRANSLATE_SYSTEM = """Translate this release-note entry from English to Dutch \
for customers of a self-hosted time-tracking app. Keep every code-like token \
(anything in backticks, ALL_CAPS identifiers, version numbers) exactly as-is. \
Answer with the Dutch sentence only — no quotes, no commentary."""

_TOKEN_RES = (
    re.compile(r"`[^`]+`"),
    # SCREAMING_SNAKE with at least one underscore: TEMPO_DATABASE__URL yes,
    # prose acronyms (VAT, CSV, API) no — those translate naturally.
    re.compile(r"\b[A-Z][A-Z0-9]*(?:_+[A-Z0-9]+)+\b"),
)


def text_hash(text_en: str) -> str:
    return hashlib.sha256(text_en.encode()).hexdigest()


def code_tokens(text: str) -> set[str]:
    return {m for rx in _TOKEN_RES for m in rx.findall(text)}


def tokens_preserved(text_en: str, text_nl: str) -> bool:
    """The check that keeps a translated breaking change actionable: every
    identifier the English mentions must appear verbatim in the Dutch."""
    return all(tok in text_nl for tok in code_tokens(text_en))


def translate_entry(text_en: str, complete) -> str:
    return complete(TRANSLATE_SYSTEM, text_en).strip().strip('"')
