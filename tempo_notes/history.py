"""Load commit history + diffs into one immutable, deterministically ordered list.

Everything downstream consumes the output of load_history() and nothing else.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_DIFF_FILE_RE = re.compile(r"^diff --git a/\S+ b/(\S+)$", re.MULTILINE)


@dataclass(frozen=True)
class Commit:
    sha: str
    author: str
    date: str  # ISO-8601, sorts lexicographically
    subject: str
    body: str
    is_merge: bool
    diff: str | None  # raw diff text, None if the commit has none
    files: tuple[str, ...] = ()  # paths touched, per the diff headers

    @property
    def file_paths(self) -> set[str]:
        return set(self.files)


def load_history(commit_files: list[Path], diffs_dir: Path) -> list[Commit]:
    """Merge one or more commit batches (initial + follow-ups) into a single
    ascending timeline.

    Deterministic by construction: sorted by (date, sha) so equal timestamps
    can never reorder between runs. Duplicate SHAs across batches collapse to
    one (first occurrence wins; batches are snapshots of the same repo).
    """
    seen: dict[str, dict] = {}
    for path in commit_files:
        for raw in json.loads(Path(path).read_text(encoding="utf-8")):
            seen.setdefault(raw["sha"], raw)

    commits: list[Commit] = []
    for raw in seen.values():
        diff_path = diffs_dir / f"{raw['sha']}.diff"
        diff = diff_path.read_text(encoding="utf-8") if diff_path.exists() else None
        commits.append(
            Commit(
                sha=raw["sha"],
                author=raw["author"],
                date=raw["date"],
                subject=raw["subject"],
                body=raw.get("body", ""),
                is_merge=raw.get("is_merge", False),
                diff=diff,
                files=tuple(_DIFF_FILE_RE.findall(diff)) if diff else (),
            )
        )
    commits.sort(key=lambda c: (c.date, c.sha))
    return commits
