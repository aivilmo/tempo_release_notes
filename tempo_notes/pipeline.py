"""Orchestration: one run of the full pipeline.

Stage order matters: everything deterministic happens before the LLM, the
ledger decides whether the LLM is consulted at all, and the validator runs
after everything, trusting nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .chains import build_chains
from .classify import find_reverts, is_dependency_bump, is_noise
from .entries import Status, derive_entries
from .generate import PROMPT_VERSION, SYSTEM, GenerationError, entry_prompt, parse_decision
from .history import load_history
from .ledger import Ledger
from .render import write_outputs
from .scope import window_for
from .translate import TRANSLATE_SYSTEM, text_hash, translate_entry, tokens_preserved
from .validate import validate_published


def _say(verbose: bool, msg: str) -> None:
    """Progress goes to stderr (flushed, so Windows consoles show it live);
    stdout stays clean for the result summary."""
    if verbose:
        print(msg, file=sys.stderr, flush=True)


def run_pipeline(commit_files: list[Path], diffs_dir: Path, version: str,
                 out_dir: Path, complete, translate_complete,
                 restore: list[str] = (), verbose: bool = True) -> dict:
    commits = load_history(commit_files, diffs_dir)
    _say(verbose, f"[1/6] loaded {len(commits)} commits from {len(commit_files)} batch(es)")
    window = window_for(commits, version)
    _say(verbose, f"[2/6] release {window.version}: window "
                  f"({window.start_date or 'history start'} .. {window.end_date}]")
    entries = derive_entries(commits, build_chains(commits), window)
    by_status = {}
    for e in entries:
        by_status[e.status.value] = by_status.get(e.status.value, 0) + 1
    _say(verbose, f"[3/6] {len(entries)} entries derived: {by_status}")

    ledger = Ledger.load(out_dir / "ledger.json")
    todo = sum(1 for e in entries
               if e.status is Status.CANDIDATE and not ledger.reusable(window.version, e))
    _say(verbose, f"[4/6] ledger run {ledger.run}: {len(ledger.records)} frozen record(s); "
                  f"{todo} entr(ies) need the LLM")
    for key in restore:
        if key not in ledger.overrides:
            ledger.overrides.append(key)

    attention, suppressed, info = [], [], []
    published, generated, reused = [], 0, 0

    for link in find_reverts(commits):
        if link.original is None:
            attention.append({"title": f"Untraceable revert {link.revert.sha}",
                              "detail": link.reason})

    for e in entries:
        rec = ledger.reusable(window.version, e)
        if rec:
            reused += 1
        elif e.status is Status.CANDIDATE:
            try:
                _say(verbose, f"      llm [{generated + 1}/{todo}] {e.scoped[0].subject[:60]}")
                decision = parse_decision(complete(SYSTEM, entry_prompt(e)))
                rec = ledger.record(window.version, e, decision, PROMPT_VERSION)
                generated += 1
            except GenerationError as err:  # not recorded => retried next run
                attention.append({"title": f"Generation failed for chain {e.chain_key}",
                                  "detail": f"{err} — entry withheld, will retry."})
                continue
        else:
            # Suppressed statuses keep the previously frozen text (if any):
            # a reviewer restore must republish run-1 wording, not regenerate.
            prev = ledger.records.get(f"{window.version}:{e.chain_key}")
            decision = dict(prev["decision"]) if prev else \
                {"breaking": False, "section": "changed", "text_en": None}
            decision.update(publish=False, skip_reason=e.status.value)
            rec = ledger.record(window.version, e, decision, PROMPT_VERSION)

        rec["_chain_key"] = e.chain_key
        d = rec["decision"]

        if e.status is Status.RETRACTED:
            if e.chain_key in ledger.overrides and d.get("text_en"):
                d["publish"] = True
                info.append({"title": f"Entry {e.chain_key} restored by reviewer",
                             "detail": "Published despite the revert, per --restore-entry."})
            else:
                attention.append({
                    "title": f'Suppressed: "{d.get("text_en") or e.scoped[0].subject}"',
                    "detail": (f"Evidence: {'; '.join(e.evidence)}\n"
                               f"Default applied: treated as never shipped in {window.version}. "
                               f"If it did reach customers, rerun with "
                               f"--restore-entry {e.chain_key}.")})
        elif e.status is Status.GATED_OFF:
            suppressed.append({"title": f"Not announced: {e.scoped[0].subject}",
                               "detail": "; ".join(e.evidence)})
        elif e.status is Status.CANCELLED:
            info.append({"title": f"Net zero inside the window: {e.scoped[0].subject}",
                         "detail": "; ".join(e.evidence)})
        elif e.status is Status.CANDIDATE and not d["publish"]:
            info.append({"title": f"Skipped: {e.scoped[0].subject}",
                         "detail": d.get("skip_reason") or "not customer-visible"})

        if d.get("publish"):
            published.append(rec)

    # Dutch: derived from frozen English, cached by its hash.
    pending_nl = sum(1 for r in published
                     if r.get("nl_of") != text_hash(r["decision"]["text_en"]))
    _say(verbose, f"[5/6] translating {pending_nl} entr(ies) to Dutch "
                  f"({len(published) - pending_nl} cached)")
    for rec in published:
        h = text_hash(rec["decision"]["text_en"])
        if rec.get("nl_of") != h:
            try:
                nl = translate_entry(rec["decision"]["text_en"], translate_complete)
            except GenerationError as err:
                rec["text_nl"], rec["nl_of"] = None, None
                attention.append({"title": f"Translation failed for {rec['_chain_key']}",
                                  "detail": f"{err} — English text shown on the NL page; retried next run."})
                continue
            if tokens_preserved(rec["decision"]["text_en"], nl):
                rec["text_nl"], rec["nl_of"] = nl, h
            else:
                rec["text_nl"], rec["nl_of"] = None, None
                attention.append({"title": f"Dutch translation rejected for {rec['_chain_key']}",
                                  "detail": "A code token was altered; English text shown on the NL page."})

    for key, problem in validate_published(published, {c.sha for c in commits}):
        _say(verbose, f"      validator pulled {key}: {problem}")
        attention.append({"title": f"Validator pulled entry {key}", "detail": problem})
        published = [r for r in published if r["_chain_key"] != key]

    noise = [c for c in commits if window.contains(c) and is_noise(c)]
    deps = [c for c in commits if window.contains(c) and is_dependency_bump(c)]
    after = [c for c in commits if c.date > window.end_date]
    stability = [
        f"{reused} entr(ies) reused from the ledger, byte-identical; {generated} newly generated.",
        f"{len(after)} commit(s) after the {window.version} bump: scoped to the next release.",
        f"{len(noise)} noise and {len(deps)} dependency commit(s) excluded (listed in traceability.json).",
    ]

    groups = {"attention": attention, "suppressed": suppressed,
              "info": info, "stability": stability}
    for rec in ledger.records.values():
        rec.pop("_chain_key", None)
    ledger.save()  # state first: generated text survives even if rendering fails
    _say(verbose, f"[6/6] ledger saved (run {ledger.run}); rendering outputs")
    files = write_outputs(out_dir, window.version, ledger.run, published, groups,
                          ledger.records)
    return {"published": len(published), "generated": generated, "reused": reused,
            "attention": len(attention), "files": files, "run": ledger.run,
            "fresh_ledger": ledger.run == 1}
