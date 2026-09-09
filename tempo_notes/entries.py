"""Derive release-note entries from chains.

This is where requirements 1, 3 and 4 meet:

- A chain is the full code story (may cross release boundaries).
- An entry is what one release publishes about that story: derived only from
  the chain's commits inside the window ("scoped").
- Commits outside the window affect the entry only if they INVALIDATE it
  (a revert of a scoped commit). A later ordinary fix continues the story in
  the next release and must not touch this entry — so it is kept out of the
  cache key on purpose.
- cache_key = facts only (scoped shas + diffs + invalidators). Nothing about
  the app (prompt version, code version) is in the key: improving the app
  never silently rewords published text.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum

from .chains import Chain
from .classify import STRICT, Kind, Policy, RevertLink, classify, find_reverts
from .flags import final_flag_values, flag_assignments
from .history import Commit
from .scope import ReleaseWindow, is_version_marker

# Subject types that can carry user-visible change. docs/test/style/ci/build
# never publish on their own; refactor stays because breaking changes hide
# there (b6cb7554c in the sample data). A BREAKING CHANGE body always wins.
_PUBLISHABLE_TYPES = ("feat", "fix", "perf", "chore", "refactor")
_TYPE_RE = re.compile(r"^(\w+)(?:\([^)]*\))?!?: ")


class Status(Enum):
    CANDIDATE = "candidate"            # goes to the LLM for wording
    CANCELLED = "cancelled_in_window"  # feat+revert both inside: net zero, informational
    RETRACTED = "retracted"            # reverted after the window: suppressed, reviewer confirms
    GATED_OFF = "gated_off"            # shipped with its feature flag off: not announced
    NOT_USER_FACING = "not_user_facing"


@dataclass(frozen=True)
class Entry:
    chain_key: str
    status: Status
    scoped: tuple[Commit, ...]        # chain ∩ window
    effective: tuple[Commit, ...]     # what the LLM will actually describe
    invalidators: tuple[Commit, ...]  # out-of-window commits that changed our mind
    evidence: tuple[str, ...]         # citable reasons, for the review report
    cache_key: str


def _publishable(c: Commit, policy: Policy = STRICT) -> bool:
    if "BREAKING CHANGE" in c.body:
        return True
    if is_version_marker(c):
        return False  # version markers are scaffolding, not news
    if classify(c) is Kind.UNCLASSIFIED:
        # Only reachable under a flexible policy — a strict one already kept
        # this commit out of the chain. Its subject carries no type to judge,
        # so it goes to the LLM as a candidate and is judged on its diff.
        return policy.flexible
    m = _TYPE_RE.match(c.subject)
    return bool(m) and m.group(1) in _PUBLISHABLE_TYPES


def _cache_key(scoped: tuple[Commit, ...], invalidators: tuple[Commit, ...],
               flag_sig: tuple[str, ...] = ()) -> str:
    h = hashlib.sha256()
    for c in scoped:
        h.update(c.sha.encode())
        h.update((c.diff or "").encode())
    for c in invalidators:
        h.update(b"!")
        h.update(c.sha.encode())
    for f in flag_sig:  # e.g. "FEATURE_ICAL_EXPORT=False" — a flag flip is a fact too
        h.update(b"~")
        h.update(f.encode())
    return h.hexdigest()


def derive_entry(chain: Chain, window: ReleaseWindow,
                 reverts: list[RevertLink],
                 window_flags: dict[str, bool],
                 policy: Policy = STRICT) -> Entry | None:
    scoped = tuple(c for c in chain if window.contains(c))
    if not scoped:
        return None  # this chain has nothing to say about this release

    reverted_by = {l.original.sha: l for l in reverts if l.original}

    # Flags this chain introduces + the value the window shipped them with.
    # Part of the cache key: a later flip of our flag is a fact about us.
    introduced = {name for c in scoped for name in flag_assignments(c)}
    flag_sig = tuple(f"{n}={window_flags[n]}" for n in sorted(introduced)
                     if n in window_flags)

    def make(status, effective=(), invalidators=(), evidence=()):
        return Entry(chain.key, status, scoped, tuple(effective),
                     tuple(invalidators), tuple(evidence),
                     _cache_key(scoped, tuple(invalidators), flag_sig))

    # 1. Is the chain's founding commit undone?
    founder = scoped[0]
    link = reverted_by.get(founder.sha)
    if link:
        quote = link.revert.body.strip() or link.revert.subject
        if window.contains(link.revert):
            return make(Status.CANCELLED,
                        evidence=[f"{link.revert.sha} reverts {founder.sha} inside the window: \"{quote}\""])
        return make(Status.RETRACTED, invalidators=[link.revert],
                    evidence=[f"{link.revert.sha} (after the window) reverts {founder.sha}: \"{quote}\""])

    # 2. Did it ship behind a flag that stayed off?
    off = sorted(n for n in introduced if window_flags.get(n) is False)
    if off:
        return make(Status.GATED_OFF,
                    evidence=[f"flag {n} is False at the end of the window" for n in off])

    # 3. Normal path: keep the publishable commits, drop in-window revert pairs.
    cancelled = {l.original.sha for l in reverts if l.original} | \
                {l.revert.sha for l in reverts if l.original and window.contains(l.revert)}
    effective = tuple(c for c in scoped
                      if _publishable(c, policy) and c.sha not in cancelled)
    if not effective:
        return make(Status.NOT_USER_FACING)
    return make(Status.CANDIDATE, effective=effective)


def derive_entries(commits: list[Commit], chains: list[Chain],
                   window: ReleaseWindow, policy: Policy = STRICT) -> list[Entry]:
    reverts = find_reverts(commits)
    window_flags = final_flag_values([c for c in commits if window.contains(c)])
    entries = []
    for chain in chains:
        entry = derive_entry(chain, window, reverts, window_flags, policy)
        if entry:
            entries.append(entry)
    return entries
