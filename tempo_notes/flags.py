"""Feature-flag tracking from diffs.

We never reconstruct whole files. We track one thing: assignments of
SCREAMING_SNAKE symbols to True/False on added lines. The last assignment
inside the release window is the value the release shipped with.
"""
from __future__ import annotations

import re

from .history import Commit

_FLAG_ASSIGN_RE = re.compile(
    r"^\+\s*([A-Z][A-Z0-9_]{2,})\s*=\s*(True|False)\b", re.MULTILINE
)


def flag_assignments(commit: Commit) -> dict[str, bool]:
    """Flags this commit sets (added lines only; context lines don't count)."""
    if not commit.diff:
        return {}
    return {
        name: value == "True"
        for name, value in _FLAG_ASSIGN_RE.findall(commit.diff)
    }


def final_flag_values(commits: list[Commit]) -> dict[str, bool]:
    """Last assignment wins. `commits` must be ascending (load_history order)."""
    values: dict[str, bool] = {}
    for c in commits:
        values.update(flag_assignments(c))
    return values
