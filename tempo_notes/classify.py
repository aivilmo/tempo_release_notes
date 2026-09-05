"""Deterministic commit classification: noise filtering and revert matching.

These decisions are made by code, never by the LLM, so that two runs over the
same history always classify identically (requirement 3), and so each decision
carries citable evidence (requirement 2).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .history import Commit

# Conventional-commit types we recognize. A closed list on purpose: an open
# `\w+:` pattern would accept junk like "asdf: stuff".
_CONVENTIONAL_RE = re.compile(
    r"^(feat|fix|perf|refactor|docs|test|chore|style|ci|build)(\([^)]*\))?!?: "
)
_REVERT_RE = re.compile(r'^Revert "(.+)"$')


def is_noise(commit: Commit) -> bool:
    """Noise = not a merge, not a revert, and no conventional subject.

    In the sample data every such commit ("wip", "asdf", "oops", ...) carries a
    placeholder diff. We still record them as 'excluded' in the traceability
    output rather than dropping them silently.
    """
    if commit.is_merge:
        return False
    if _REVERT_RE.match(commit.subject):
        return False
    return not _CONVENTIONAL_RE.match(commit.subject)


def is_dependency_bump(commit: Commit) -> bool:
    """chore(deps) commits may not bridge chains (pyproject.toml is a hub file)."""
    return commit.subject.startswith("chore(deps)")


@dataclass(frozen=True)
class RevertLink:
    revert: Commit
    original: Commit | None   # None => could not be traced: flag to reviewer
    reason: str               # evidence for the review report


def find_reverts(commits: list[Commit]) -> list[RevertLink]:
    """Match `Revert "<subject>"` commits to the commit they undo.

    Candidates are earlier commits with the exact quoted subject. Ties are
    broken by (1) sharing touched files with the revert, (2) most recent.
    An unmatched revert is returned with original=None — requirement 2 says
    untraceable things get surfaced, not ignored.
    """
    links: list[RevertLink] = []
    for i, c in enumerate(commits):
        m = _REVERT_RE.match(c.subject)
        if not m:
            continue
        quoted = m.group(1)
        candidates = [p for p in commits[:i] if p.subject == quoted]
        if not candidates:
            links.append(RevertLink(c, None, f'no earlier commit with subject "{quoted}"'))
            continue
        overlapping = [p for p in candidates if p.file_paths & c.file_paths]
        pool = overlapping or candidates
        original = pool[-1]  # most recent qualifying candidate
        why = "subject + file overlap" if overlapping else "subject match only"
        links.append(RevertLink(c, original, why))
    return links
