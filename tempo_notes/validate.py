"""Independent post-generation checks (requirement 2: the app must catch an
entry that can't be traced). Runs after everything else, trusts nothing.
"""
from __future__ import annotations

from .translate import tokens_preserved


def validate_published(published: list[dict], known_shas: set[str]) -> list[tuple[str, str]]:
    """Returns (chain_key, problem). A flagged record is pulled from the page."""
    problems = []
    for key, rec in ((r["_chain_key"], r) for r in published):
        d = rec["decision"]
        if not d.get("text_en"):
            problems.append((key, "published entry has no text"))
        missing = [s for s in rec["source_shas"] if s not in known_shas]
        if missing:
            problems.append((key, f"cites commits not in the history: {missing}"))
        if rec.get("text_nl") and not tokens_preserved(d["text_en"], rec["text_nl"]):
            problems.append((key, "Dutch translation lost a code token"))
    return problems
