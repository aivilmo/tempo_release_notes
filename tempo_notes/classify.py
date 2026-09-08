"""Deterministic commit classification: kind, noise filtering and revert matching.

These decisions are made by code, never by the LLM, so that two runs over the
same history always classify identically (requirement 3), and so each decision
carries citable evidence (requirement 2).

Two things are deliberately kept apart here, because conflating them is how a
history that doesn't use conventional commits ends up publishing a blank page:

- NOISE is a commit with no information to publish ("wip", "oops"). It is
  recognised by an explicit lexicon of contentless subjects, not by the
  absence of a prefix.
- UNCLASSIFIED is a real change whose author simply didn't write a
  conventional subject ("closes #412"). In a repo that uses conventional
  commits these are almost always throwaway too; in a repo that doesn't, they
  are the entire history.

Which of the two gets excluded is a policy decision, not a fact about the
commit — see `Policy` and `policy_for`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .history import Commit

# Conventional-commit types we recognize. A closed list on purpose: an open
# `\w+:` pattern would accept junk like "asdf: stuff".
_CONVENTIONAL_RE = re.compile(
    r"^(feat|fix|perf|refactor|docs|test|chore|style|ci|build)(\([^)]*\))?!?: "
)
_REVERT_RE = re.compile(r'^Revert "(.+)"$')

# Contentless subjects: they describe the act of committing rather than a
# change to the product. Anchored to the WHOLE subject on purpose — a real
# subject is longer and more specific than these, so whole-subject matching
# is far safer than substring matching ("fix typo" is junk; "fix typos in the
# invoice template shown to customers" is not). The trailing class absorbs a
# counter or punctuation, so "wip 2" and "oops!" match too.
_JUNK_RE = re.compile(
    r"^(?:more\s+|just\s+|another\s+)?"
    r"(?:wip|temp|tmp|debug(?:ging)?|oops(?:\s+sorry)?|asdf|qwerty"
    r"|clean\s?up|tidy(?:\s?up)?|formatting|format|reformat(?:ting)?"
    r"|whitespace|lint(?:ing)?|rebas(?:e|ing)|squash|fixup|amend"
    r"|(?:fix(?:ing)?\s+)?typos?(?:\s+again)?"
    r"|nits?|minor|misc(?:ellaneous)?|stuff"
    r"|run\s+black(?:\s+over\s+the\s+codebase)?)"
    r"[\s\d\W]*$",
    re.IGNORECASE,
)


class Kind(Enum):
    """What a commit is, before any policy is applied."""

    MERGE = "merge"
    REVERT = "revert"
    CONVENTIONAL = "conventional"    # has a recognised conventional subject
    NOISE = "noise"                  # contentless: nothing to publish, ever
    UNCLASSIFIED = "unclassified"    # a real change, informally described


def classify(commit: Commit) -> Kind:
    """The commit's kind. Pure function of the subject: same input, same kind."""
    if commit.is_merge:
        return Kind.MERGE
    if _REVERT_RE.match(commit.subject):
        return Kind.REVERT
    if _CONVENTIONAL_RE.match(commit.subject):
        return Kind.CONVENTIONAL
    if _JUNK_RE.match(commit.subject.strip()):
        return Kind.NOISE
    return Kind.UNCLASSIFIED


def is_noise(commit: Commit) -> bool:
    """Contentless by its own subject — excluded under every policy."""
    return classify(commit) is Kind.NOISE


def is_unclassified(commit: Commit) -> bool:
    """No conventional subject, but not recognisably contentless either."""
    return classify(commit) is Kind.UNCLASSIFIED


def is_dependency_bump(commit: Commit) -> bool:
    """chore(deps) commits may not bridge chains (pyproject.toml is a hub file)."""
    return commit.subject.startswith("chore(deps)")


# --- policy -----------------------------------------------------------------


@dataclass(frozen=True)
class Policy:
    """How to treat commits with no conventional subject. The operator's
    call, not the app's: `--classify strict|flexible`."""

    flexible: bool      # True => UNCLASSIFIED commits can chain and publish
    rationale: str     # one line for the review report; always shown

    def excludes(self, commit: Commit) -> bool:
        """Commits kept out of chains and out of the notes entirely."""
        kind = classify(commit)
        if kind is Kind.NOISE:
            return True
        return kind is Kind.UNCLASSIFIED and not self.flexible


STRICT = Policy(False, "strict: commits with no conventional subject are excluded")
FLEXIBLE = Policy(True, "flexible: commits with no conventional subject are kept "
                       "as candidates and judged on their diffs")


def policy_for(mode: str) -> Policy:
    """Resolve `--classify strict|flexible`. Strict is the default: it is what
    a repo using conventional commits wants. A repo that doesn't use them at
    all publishes nothing under strict, which the run reports rather than
    quietly accepting — that is the signal to rerun with flexible."""
    return FLEXIBLE if mode == "flexible" else STRICT


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
