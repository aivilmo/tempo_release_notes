"""CLI. First command: dry-run — show every deterministic decision, call no LLM.

    python -m tempo_notes dry-run --version 2.1 \
        --commits data/commits.json [--commits data/commits-followup.json] \
        --diffs data/diffs
"""
from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from .chains import build_chains
from .classify import find_reverts, is_dependency_bump, is_noise
from .history import load_history
from .scope import ScopeError, resolve_window


def dry_run(args: argparse.Namespace) -> int:
    commits = load_history([Path(p) for p in args.commits], Path(args.diffs))
    try:
        window = resolve_window(commits, args.version, args.from_date, args.to_date)
    except ScopeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    in_window = [c for c in commits if window.contains(c)]
    after = [c for c in commits if c.date > window.end_date]
    noise = [c for c in in_window if is_noise(c)]
    merges = [c for c in in_window if c.is_merge]
    dep_bumps = [c for c in in_window if is_dependency_bump(c)]

    print(f"release {window.version}")
    print(f"  window: ({window.start_date or 'history start'} .. {window.end_date}]")
    print(f"  commits in window: {len(in_window)}  "
          f"(noise: {len(noise)}, merges: {len(merges)}, dep bumps: {len(dep_bumps)})")
    print(f"  commits after window (next cycle): {len(after)}")
    missing = [c for c in in_window if not c.is_merge and c.diff is None]
    if missing:
        print(f"  WARNING: {len(missing)} in-window commit(s) have no diff file — "
              f"they cannot be verified or published")

    print("\nchains touching the window (>= 2 commits):")
    for chain in build_chains(commits):
        if len(chain) < 2 or not any(window.contains(c) for c in chain):
            continue
        marks = "".join("W" if window.contains(c) else "A" for c in chain)
        print(f"  [{marks}] {', '.join(c.sha[:9] for c in chain)}")
        for c in chain:
            print(f"        {c.date[:10]} {c.subject[:72]}")

    print("\nreverts:")
    for link in find_reverts(commits):
        if link.original:
            print(f"  {link.revert.sha[:9]} undoes {link.original.sha[:9]} ({link.reason})")
        else:
            print(f"  {link.revert.sha[:9]} UNMATCHED — {link.reason}  -> review report")

    print("\nnoise excluded (recorded, not silently dropped):")
    for c in noise:
        print(f"  {c.sha[:9]} {c.subject[:60]}")
    return 0


def show_entries(args: argparse.Namespace) -> int:
    from .entries import derive_entries

    commits = load_history([Path(p) for p in args.commits], Path(args.diffs))
    try:
        window = resolve_window(commits, args.version, args.from_date, args.to_date)
    except ScopeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    for e in derive_entries(commits, build_chains(commits), window):
        print(f"{e.status.value:<20} chain {e.chain_key[:9]}  key {e.cache_key[:12]}…")
        print(f"    founder: {e.scoped[0].subject[:70]}")
        for c in e.effective:
            print(f"    tells:   {c.sha[:9]} {c.subject[:64]}")
        for ev in e.evidence:
            print(f"    because: {ev[:100]}")
    return 0


def _common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--version", required=True, help="release to cover, e.g. 2.1")
    p.add_argument("--commits", action="append", required=True,
                   help="commit batch (repeat for follow-ups)")
    p.add_argument("--diffs", required=True, help="directory with <sha>.diff files")
    p.add_argument("--from", dest="from_date", default=None,
                   help="explicit window start (exclusive; ISO date/datetime) — for histories without version markers")
    p.add_argument("--to", dest="to_date", default=None,
                   help="explicit window end (inclusive; ISO date/datetime); --version then only labels the outputs")


def generate_cmd(args: argparse.Namespace) -> int:
    from .generate import GenerationError, openrouter_client
    from .pipeline import run_pipeline

    try:
        complete = openrouter_client(args.model)
        summary = run_pipeline(
            [Path(p) for p in args.commits], Path(args.diffs), args.version,
            Path(args.out), complete, complete, restore=args.restore_entry or [],
            from_date=args.from_date, to_date=args.to_date)
    except (ScopeError, GenerationError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"published: {summary['published']}  generated: {summary['generated']}  "
          f"reused: {summary['reused']}  needs attention: {summary['attention']}")
    for f in summary["files"]:
        print(f"  wrote {f}")
    if not args.no_open:
        review = next((f for f in summary["files"] if Path(f).name == "review.html"), None)
        if review:
            # Best-effort: a clean/headless machine (CI, a server with no
            # display) has no browser to open, and that's not a reason to
            # fail a generate that already succeeded.
            try:
                opened = webbrowser.open(Path(review).resolve().as_uri())
            except webbrowser.Error:
                opened = False
            if not opened:
                print(f"  (couldn't open a browser automatically — open {review} yourself)",
                      file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="tempo_notes")
    sub = parser.add_subparsers(dest="command", required=True)
    dr = sub.add_parser("dry-run", help="report every deterministic decision; no LLM calls")
    _common_args(dr)
    dr.set_defaults(func=dry_run)
    en = sub.add_parser("entries", help="show derived entries with status and cache key")
    _common_args(en)
    en.set_defaults(func=show_entries)
    ge = sub.add_parser("generate", help="produce the notes, review report and traceability")
    _common_args(ge)
    ge.add_argument("--out", default="out", help="output directory (holds ledger.json)")
    ge.add_argument("--model", default="anthropic/claude-sonnet-4.5",
                    help="OpenRouter model id")
    ge.add_argument("--restore-entry", action="append",
                    help="reviewer override: publish a retracted entry (chain key)")
    ge.add_argument("--no-open", action="store_true",
                    help="don't automatically open review.html when done")
    ge.set_defaults(func=generate_cmd)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
