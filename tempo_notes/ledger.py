"""The ledger: everything ever decided or written, keyed by chain.

This file (out/ledger.json) is first-class state, not an optimization cache.
Published text can only be re-derived from here — a clean run on another
machine would word things differently, so the guarantee we give is:
the first run fixes the text; every later run over the same history is
byte-identical; only invalidating facts (a changed cache_key) reopen an entry.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .entries import Entry


@dataclass
class Ledger:
    path: Path
    run: int = 1
    records: dict[str, dict] = field(default_factory=dict)   # chain_key -> record
    overrides: list[str] = field(default_factory=list)       # reviewer --restore-entry

    @classmethod
    def load(cls, path: Path) -> "Ledger":
        if not path.exists():
            return cls(path=path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(path=path, run=raw["run"] + 1,
                   records=raw["records"], overrides=raw.get("overrides", []))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(
            {"run": self.run, "records": self.records, "overrides": self.overrides},
            indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

    @staticmethod
    def _key(release: str, entry: Entry) -> str:
        # Namespaced per release: the same chain publishes different entries
        # in different releases, and one must never overwrite the other.
        return f"{release}:{entry.chain_key}"

    def reusable(self, release: str, entry: Entry) -> dict | None:
        """Frozen record for this entry, iff the facts haven't moved."""
        rec = self.records.get(self._key(release, entry))
        if rec and rec["cache_key"] == entry.cache_key:
            return rec
        return None

    def record(self, release: str, entry: Entry, decision: dict,
               prompt_version: str) -> dict:
        prev = self.records.get(self._key(release, entry))
        rec = {
            "cache_key": entry.cache_key,
            "status": entry.status.value,
            "decision": decision,               # publish/skip, section, text_en, ...
            "text_nl": prev.get("text_nl") if prev else None,
            "source_shas": [c.sha for c in entry.scoped],
            "invalidators": [c.sha for c in entry.invalidators],
            "evidence": list(entry.evidence),
            "generated_by_prompt": prompt_version,
            "first_run": prev["first_run"] if prev else self.run,
            "last_changed_run": self.run,
        }
        self.records[self._key(release, entry)] = rec
        return rec
