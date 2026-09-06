"""Group commits into chains: commits that touch the same files tell one story.

Two guards against over-grouping (both observed on the sample data):
- noise commits never enter the graph (a real-world "run black over the
  codebase" touches everything and would collapse all chains into one);
- chore(deps) commits join no one (hub files like pyproject.toml would
  otherwise fuse unrelated dependency bumps into one chain).

Chain membership is structural context. Which commits of a chain end up in a
given release's entry is decided later, by the release window.
"""
from __future__ import annotations

from collections import defaultdict

from .classify import is_dependency_bump, is_noise
from .history import Commit


class Chain(tuple):
    """An ascending tuple of commits sharing files. Deterministic identity."""

    @property
    def key(self) -> str:
        return self[0].sha  # oldest member names the chain


def build_chains(commits: list[Commit]) -> list[Chain]:
    linkable = [
        c for c in commits
        if c.diff and not is_noise(c) and not is_dependency_bump(c)
    ]

    parent = {c.sha: c.sha for c in linkable}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    file_owner: dict[str, str] = {}
    for c in linkable:  # ascending order => deterministic unions
        for path in sorted(c.file_paths):
            if path in file_owner:
                parent[find(file_owner[path])] = find(c.sha)
            file_owner[path] = c.sha

    groups: dict[str, list[Commit]] = defaultdict(list)
    for c in linkable:
        groups[find(c.sha)].append(c)

    chains = [Chain(sorted(g, key=lambda c: (c.date, c.sha))) for g in groups.values()]
    chains.sort(key=lambda ch: (ch[0].date, ch[0].sha))
    return chains
