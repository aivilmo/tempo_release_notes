"""Derive the commit window for a release from 'bump version to X.Y.Z' markers.

Policy: never guess. If the requested version has no marker, we stop with a
clear message instead of producing silently wrong notes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .history import Commit

_BUMP_RE = re.compile(r"bump version to (\d+\.\d+\.\d+)", re.IGNORECASE)


class ScopeError(Exception):
    """Raised when the release window cannot be established from the data."""


@dataclass(frozen=True)
class ReleaseWindow:
    version: str            # normalized, e.g. "2.1.0"
    start_date: str | None  # previous bump's date (exclusive); None = history start
    end_date: str           # this version's bump date (inclusive)

    def contains(self, commit: Commit) -> bool:
        after_start = self.start_date is None or commit.date > self.start_date
        return after_start and commit.date <= self.end_date


def find_bumps(commits: list[Commit]) -> list[tuple[str, Commit]]:
    """All version markers, in timeline order."""
    bumps = []
    for c in commits:
        m = _BUMP_RE.search(c.subject)
        if m:
            bumps.append((m.group(1), c))
    return bumps


def window_for(commits: list[Commit], target: str) -> ReleaseWindow:
    """Window for `target` ("2.1" means the 2.1.0 release)."""
    bumps = find_bumps(commits)
    if not bumps:
        raise ScopeError(
            "No 'bump version to X.Y.Z' markers found in the history. "
            "Pass an explicit window with --from/--to."
        )

    wanted = {target, f"{target}.0"}
    matches = [(v, c) for v, c in bumps if v in wanted]
    if not matches:
        known = ", ".join(v for v, _ in bumps)
        raise ScopeError(
            f"No version marker for '{target}'. Markers found: {known}. "
            "Pass an explicit window with --from/--to."
        )
    version, bump_commit = matches[-1]

    previous = [c for v, c in bumps if c.date < bump_commit.date]
    start_date = previous[-1].date if previous else None
    return ReleaseWindow(version=version, start_date=start_date, end_date=bump_commit.date)
