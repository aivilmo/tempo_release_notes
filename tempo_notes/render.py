"""Render the four outputs from the ledger. Pure formatting — every decision
was already made and recorded upstream, so rendering is trivially deterministic.
"""
from __future__ import annotations

import json
from pathlib import Path

_SECTIONS = (("changed", "What's changed", "Wat is er veranderd"),
             ("improved", "What's improved", "Wat is er verbeterd"),
             ("fixed", "What's fixed", "Wat is er opgelost"))


def _page(version: str, published: list[dict], lang: str) -> str:
    lines = [f"# Tempo {version}", ""]
    breaking = []
    for rec in published:
        if rec["decision"]["breaking"]:
            breaking.append(rec["decision"]["text_en"] if lang == "en" else
                            (rec.get("text_nl") or rec["decision"]["text_en"]))
    if breaking:
        # One banner, however many actions: self-hosted admins read it once,
        # everyone else scrolls past one block instead of several.
        header = ("Before you upgrade — action required" if lang == "en"
                  else "Vóór het upgraden — actie vereist")
        lines += [f"> ⚠ **{header}**", ">"]
        lines += [f"> - {text}" for text in breaking]
        lines += [""]
    for key, title_en, title_nl in _SECTIONS:
        body = []
        for rec in published:
            d = rec["decision"]
            if d["breaking"] or d["section"] != key:
                continue
            text = d["text_en"] if lang == "en" else (rec.get("text_nl") or d["text_en"])
            body.append(f"- {text}")
        if body:
            lines += [f"## {title_en if lang == 'en' else title_nl}", "", *body, ""]
    return "\n".join(lines)


def _review_report(version: str, run: int, groups: dict) -> str:
    L = [f"# Review report — Tempo {version}, run {run}", ""]
    attention = groups["attention"]
    L += [f"{len(attention)} item(s) need your attention." if attention
          else "Nothing needs your attention.", ""]
    for title, items in (("⚠ Needs confirmation", attention),
                         ("Suppressed (no action expected)", groups["suppressed"]),
                         ("Informational", groups["info"])):
        if not items:
            continue
        L += [f"## {title}", ""]
        for it in items:
            L += [f"### {it['title']}", it["detail"], ""]
    L += ["## Stability summary", ""]
    for line in groups["stability"]:
        L.append(f"- {line}")
    L.append("")
    return "\n".join(L)


def write_outputs(out_dir: Path, version: str, run: int,
                  published: list[dict], groups: dict,
                  ledger_records: dict) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        out_dir / f"release_notes_v{version}.en.md": _page(version, published, "en"),
        out_dir / f"release_notes_v{version}.nl.md": _page(version, published, "nl"),
        out_dir / "review_report.md": _review_report(version, run, groups),
        out_dir / "traceability.json": json.dumps(
            ledger_records, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    }
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
    return list(files)
