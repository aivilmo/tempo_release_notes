"""Derive the commit window for a release from version markers.

Policy: never guess. If the requested version has no marker, we stop with a
clear message instead of producing silently wrong notes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .history import Commit

# An optional conventional-commit prefix ("chore: ", "chore(release)!: ").
_CONV = r"(?:[a-z]+(?:\([^)]*\))?!?:\s*)?"
_V = r"v?(\d+\.\d+\.\d+)"


@dataclass(frozen=True)
class _Strategy:
    name: str
    pattern: re.Pattern


# Ordered most specific first. Each is anchored end-to-end on purpose.
_STRATEGIES: tuple[_Strategy, ...] = (
    _Strategy("'bump version to X.Y.Z'",
              re.compile(rf"^{_CONV}bump version to {_V}$", re.I)),
    _Strategy("'bump version: A -> B' (bump2version)",
              re.compile(rf"^{_CONV}bump version:\s*\S+\s*(?:->|→|to)\s*{_V}$", re.I)),
    _Strategy("'<type>(release): X.Y.Z'",
              re.compile(rf"^[a-z]+\(release\)!?:\s*{_V}$", re.I)),
    _Strategy("'release X.Y.Z'",
              re.compile(rf"^{_CONV}release:?\s+{_V}$", re.I)),
    _Strategy("a bare version subject",
              re.compile(rf"^{_V}$", re.I)),
)

_TAG_RE = re.compile(rf"^{_V}$", re.I)


class ScopeError(Exception):
    """Raised when the release window cannot be established from the data."""


@dataclass(frozen=True)
class ReleaseWindow:
    version: str            # normalized, e.g. "2.1.0"
    start_date: str | None  # previous bump's date (exclusive); None = history start
    end_date: str           # this version's bump date (inclusive)
    marker: str = "explicit --from/--to"  # how the window was established

    def contains(self, commit: Commit) -> bool:
        after_start = self.start_date is None or commit.date > self.start_date
        return after_start and commit.date <= self.end_date


def is_version_marker(commit: Commit) -> bool:
    """True if this commit is release scaffolding under ANY strategy.

    Deliberately broader than the strategy that won: a subject that is purely
    a version number is never a release note, whichever convention produced
    it, so `entries.py` suppresses all of them.
    """
    subject = commit.subject.strip()
    return any(s.pattern.match(subject) for s in _STRATEGIES)


def _tagged_versions(commit: Commit) -> list[str]:
    """Versions from git tags, when the input data carries them. Tags are the
    authoritative record of what was released, so they outrank any subject."""
    out = []
    for tag in commit.tags:
        m = _TAG_RE.match(tag.strip())
        if m:
            out.append(m.group(1))
    return out


def detect_markers(commits: list[Commit]) -> tuple[list[tuple[str, Commit]], str]:
    """All version markers in timeline order, plus how they were found."""
    tagged = [(v, c) for c in commits for v in _tagged_versions(c)]
    if tagged:
        return tagged, "git tags in the commit data"
    for strategy in _STRATEGIES:
        found = []
        for c in commits:
            m = strategy.pattern.match(c.subject.strip())
            if m:
                found.append((m.group(1), c))
        if found:
            return found, f"subjects matching {strategy.name}"
    return [], "no version markers found"


def find_bumps(commits: list[Commit]) -> list[tuple[str, Commit]]:
    """All version markers, in timeline order."""
    return detect_markers(commits)[0]


def window_for(commits: list[Commit], target: str) -> ReleaseWindow:
    """Window for `target` ("2.1" means the 2.1.0 release)."""
    bumps, how = detect_markers(commits)
    tried = "; ".join(s.name for s in _STRATEGIES)
    if not bumps:
        raise ScopeError(
            f"No version markers found in the history. Tried: {tried}. "
            "Pass an explicit window with --from/--to."
        )

    wanted = {target, f"{target}.0"}
    matches = [(v, c) for v, c in bumps if v in wanted]
    if not matches:
        known = ", ".join(v for v, _ in bumps)
        raise ScopeError(
            f"No version marker for '{target}'. Found markers via {how}: {known}. "
            "Pass an explicit window with --from/--to."
        )
    version, bump_commit = matches[-1]

    previous = [c for v, c in bumps if c.date < bump_commit.date]
    start_date = previous[-1].date if previous else None
    return ReleaseWindow(version=version, start_date=start_date,
                         end_date=bump_commit.date, marker=how)


def _widen_day(date: str, end: bool) -> str:
    """A bare YYYY-MM-DD means the whole day: as --to it must cover 23:59."""
    return date + ("T23:59:59Z" if end and len(date) == 10 else "")


def resolve_window(commits: list[Commit], target: str,
                   start: str | None = None, end: str | None = None) -> ReleaseWindow:
    """Version markers by default; an explicit window when the operator
    states one (--from exclusive, --to inclusive, ISO dates or datetimes).
    `target` then only labels the output files."""
    if end:
        return ReleaseWindow(version=target,
                             start_date=_widen_day(start, False) if start else None,
                             end_date=_widen_day(end, True))
    if start:
        raise ScopeError("--from needs --to as well.")
    return window_for(commits, target)
