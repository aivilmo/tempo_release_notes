# Tempo release notes generator

Turns Tempo's commit history into customer-facing release notes for a given
version, in English and Dutch, with full traceability from every published
line back to the commits that justify it.

Built for the constraints that matter in this problem, in this order: what we
publish is **true** (grounded in diffs, not commit-message claims), every line
is **traceable** to commits, the same history always produces the **same
notes**, and a late batch of commits **corrects** the published notes without
rewording what didn't change.

## Setup (clean machine)

Requirements: Python 3.10+. No third-party dependencies — standard library only.

```bash
git clone <this repo> && cd tempo-notes
export OPENROUTER_API_KEY=sk-or-...
```

```powershell
git clone <this repo>; cd tempo-notes
$env:OPENROUTER_API_KEY = "sk-or-..."
```

That's it. There is nothing to install.

## Usage

Commands are single-line so they work in bash, PowerShell and cmd alike.
If `python` is not on your PATH as Python 3, use `python3`.

```bash
# 1. Inspect every deterministic decision first — no LLM calls, costs nothing:
python -m tempo_notes dry-run --version 2.1 --commits data/commits.json --diffs data/diffs

# 2. Generate the notes:
python -m tempo_notes generate --version 2.1 --commits data/commits.json --diffs data/diffs --out out

# 3. When a follow-up batch of commits arrives, add it and rerun:
python -m tempo_notes generate --version 2.1 --commits data/commits.json --commits data/commits-followup.json --diffs data/diffs --out out
```

Outputs in `out/`:

| file | what it is |
|---|---|
| `release_notes_v<V>.en.md` | the public notes, English — publishable as-is |
| `release_notes_v<V>.nl.md` | Dutch, derived per-entry from the frozen English |
| `release_notes_v<V>.html` | the public page: both languages in one file, EN/NL toggle |
| `review.html` | for the human approver: what needs a decision, a preview of the public page, a quiet log of everything else |
| `review_report.md` | the same review content as `review.html`, plain text |
| `traceability.json` | one record per entry: text, source SHAs, evidence, cache key |
| `ledger.json` | internal state — see "The ledger" below. Keep it. |

Useful extras: `entries` (like dry-run, but shows derived entries with status
and cache key), `--model <openrouter-id>` (default `anthropic/claude-sonnet-4.5`),
`--restore-entry <chain-key>` (reviewer override, explained below),
`--from <date> --to <date>` (explicit window for histories without version
markers; `--to` is inclusive, `--version` then only labels the outputs),
`--classify strict|flexible` (how to treat commits with no conventional
subject — see "Classify" below; `dry-run` shows the effect before you spend
anything), and `--no-open` (skip auto-opening `review.html` — `generate` opens
it in your default browser when it's done; harmless best-effort on a headless
machine).

Tests (no API key or network needed — the LLM is faked locally):

```bash
python -m unittest discover -s tests
```

## How it works

The pipeline runs in stages; **everything except wording is decided by
deterministic code, and the LLM only ever decides two things** — whether a
change is worth telling customers about, and how to phrase it. It never
decides what exists.

1. **Scope.** The release window is everything after the previous version's
   marker, up to and including the target's.

   Finding that marker is the one place the app must recognise a convention it
   didn't choose, so it tries several in priority order and reports which one
   fired. **Git tags win outright** when the commit data carries them (a
   `tags` or `refs` field per commit) — a tag is the authoritative record of
   what shipped. Otherwise it falls back to subject patterns:
   `bump version to X.Y.Z`, bump2version's `Bump version: A → B`,
   `<type>(release): X.Y.Z`, `release X.Y.Z`, and a bare `vX.Y.Z` subject.

   Two rules keep that from becoming a soup of regexes. **Every pattern is
   anchored to the whole subject** — this history has ~1000 commits like
   `chore(deps): bump pillow from 10.2.0 to 10.3.0`, and a loose
   "bump … to X.Y.Z" would match every one of them and produce a nonsense
   window. **The first strategy that finds anything wins, and only its matches
   are used**, so a looser pattern can never pollute a history where a tighter
   one already worked.

   If the target version has no marker, the app stops with a clear error
   listing what it tried, rather than guessing; the operator can state the
   window explicitly with `--from/--to`.
2. **Classify.** Every commit gets a *kind*, and two of them are deliberately
   kept apart:

   - **noise** — a contentless subject that describes the act of committing
     rather than a change (`wip`, `oops`, `formatting`, `fix typo`). Matched
     against an explicit lexicon, anchored to the whole subject so that
     "fix typos in the invoice template" stays a real commit. Never published,
     under any setting.
   - **unclassified** — a real change the author described informally
     (`closes #412`, `see ticket`). In a repo that uses conventional commits
     these are almost always throwaway; in a repo that doesn't, they are the
     entire history.

   Whether unclassified commits count is a **policy**, not a fact about the
   commit, so it is the operator's call: `--classify flexible` (the default)
   keeps them as candidates and lets the LLM judge them on their diffs;
   `--classify strict` excludes them. The policy in force is always printed in
   the review report and by `dry-run`, so the choice is never silent.

   Flexible is the default because the two mistakes cost very different
   amounts. Under strict, a repository that doesn't use conventional commits
   publishes an **empty page** — a silent, total failure. Under flexible, a
   repository that does use them sends some throwaway commits to the LLM,
   which skips them on the evidence of their diffs and logs each skip for the
   reviewer. Use `strict` when a repo's conventional-commit discipline is good
   and you want the notes to lean on it.

   Everything excluded is recorded in `traceability.json`, never silently
   dropped. `Revert "<subject>"` commits are matched to the commit
   they undo (exact subject match among earlier commits; ties broken by
   file overlap, then recency). An unmatched revert is flagged to the reviewer.
3. **Chains.** Commits touching the same files are grouped (union-find over
   file collisions): a feature, its fixes, its revert and its flag flip are
   one story, even across batches. Two guards reduce over-grouping — commits
   the classification policy excludes never enter the graph, and `chore(deps)`
   commits link to no one. They are **not** sufficient on a large repository;
   see "What I cut" for the measured failure and what fixes it.
4. **Entries.** Each chain contributes at most one entry per release, derived
   only from its commits inside the window. Cross-window commits affect the
   entry only if they *invalidate* it (a revert); a later ordinary fix belongs
   to the next release and does not touch it. Features that shipped with
   their feature flag off are not announced. Each entry gets a
   `cache_key = sha256(in-window SHAs + diffs + invalidators + flag state)` —
   facts only, nothing about the app itself.
5. **Generate.** Candidates go to the LLM (via OpenRouter) with subjects,
   bodies and diffs; the prompt instructs it to trust the diff over the
   message, to skip internal-only work, and to always answer in English
   (source commits may be in any language — this history has Dutch ones).
   The decision comes back as strict JSON; anything unparseable is withheld
   and flagged, never guessed.
6. **Translate.** Dutch is derived per-entry from the frozen English text and
   cached by its hash — the two languages cannot diverge in content. A code
   check verifies every identifier (`` `db_url` ``, `TEMPO_DATABASE__URL`)
   survives translation verbatim; if not, the English text is shown on the
   NL page and the reviewer is flagged.
7. **Validate & render.** An independent validator checks every published
   line maps to a record whose SHAs exist in the input history, and pulls
   anything that fails onto the review report. Rendering is pure formatting.

## The ledger (why the notes don't reword themselves)

`out/ledger.json` is first-class state, not a cache. The first run fixes each
entry's wording; every later run reuses that text byte-for-byte unless the
entry's facts changed (its `cache_key` moved). Consequences you should know:

- **Keep `ledger.json` between runs.** Deleting it re-words everything —
  truthfully, but differently.
- The determinism guarantee is *stability given the run history*, not
  reproducibility from scratch — nothing with an LLM in the loop has that.
- One `out/` directory can hold several releases (e.g. 2.1.0 and 2.1.1):
  ledger records are namespaced per release, so generating the next version
  never touches the frozen text of the previous one.
- Improving the prompt does **not** re-word existing entries (the prompt
  version is recorded per entry, but deliberately kept out of the cache key).
  Frozen text only reopens when the underlying facts change.
- Changing `--classify` **does** re-word, and should: a different policy means
  a different set of commits, which changes chain membership and cache keys.
  Pick it once per repo rather than flipping it between runs.

## The review report (what the approver actually reads)

The app refuses to fake certainty. When the data cannot answer a question —
the canonical example in this dataset: a feature committed inside the window
and reverted 29 hours after the version bump with the note *"pulled from the
release"* — the app applies a conservative default (don't announce what may
never have reached customers: announcing a ghost feature is expensive,
omitting a one-day feature is free), and puts the decision in
`review_report.md` with the evidence quoted inline, so the approver can decide
in seconds without reading any git history. If the approver knows better,
`--restore-entry <chain-key>` republishes the original frozen wording — a
restore, not a regeneration.

## Two HTML views, two readers

`review.html` and `release_notes_v<V>.html` render the same frozen data, but
are deliberately two separate files rather than one page trying to serve both
audiences:

- **`release_notes_v<V>.html`** is what Tempo's customers see. It knows
  nothing about chains, ledgers, or review status — no line of copy about how
  the notes were produced. Language is a CSS-only toggle (no JS), so it stays
  one static file you can host anywhere.
- **`review.html`** is what the approver opens before publishing: the items
  that need a decision, a quiet collapsible log of everything the app decided
  on its own, and a preview of the public page. That preview sits inside a
  little browser-chrome box with a link to the real public file, so it always
  reads as a preview of *another* document rather than being mistaken for the
  page itself.

Both are single self-contained files — no JS beyond the language toggle, no
network calls, no build step — that open with a double click. `generate` also
opens `review.html` in your default browser as soon as it's done (best-effort;
harmless if the machine is headless — pass `--no-open` to skip it).

## What I cut, and why

- **Chain grouping that survives a repository this app hasn't seen.** This is
  the biggest known limitation, and the one I'd fix first.

  Chains group commits by *transitive* file overlap. That works cleanly on
  this dataset because its busiest file is touched by exactly **2** commits —
  file overlap is very nearly a perfect signal here. It does not survive a
  real repository. Run against a 3,363-commit codebase whose busiest file is
  touched 519 times, transitivity fuses **3,316 commits (98.6%) into a single
  chain**: one release-note bullet for the entire release, from a prompt of
  roughly 2M tokens that no model will accept.

  So the fixes are measured, not guessed. Capping file fan-out (a file touched
  by more than N commits stops linking) is **free for this dataset** — since
  the busiest file here is touched twice, any cap ≥ 3 provably cannot change
  the v2.1 notes — and on the real repo it cuts the largest chain from 3,316
  to 59 commits at cap 3, or 19 at cap 2. A time bound does **not** work: a
  hub file is touched every ~1.3 days, so consecutive touches always look
  recent and the chain propagates anyway. Hunk-level overlap would be better
  than either, and costs more than both.

- **A bound on total prompt size.** `entry_prompt` truncates each diff to
  4,000 characters but never limits how many commits one entry may describe,
  so prompt size is unbounded in the number of commits per chain. That is what
  actually fails first on a large repo, and it wants a budget across the whole
  prompt rather than per diff — independent of the chaining fix above.

- **A degenerate-chain guard.** A chain holding most of a release is evidence
  that grouping failed, not that the release is one story. It should reach the
  reviewer as an attention item — the same "surface it, never guess" rule the
  rest of the app follows — instead of being summarised into a single entry.
- **Revert-of-revert.** Detected and flagged to the reviewer, not resolved
  automatically. Rare enough that a human decision beats speculative logic.
- **Reverts of mid-chain commits.** A revert is checked against the chain's
  founding commit; a revert that undoes a mid-chain commit while the chain
  stays alive only cancels pairwise inside the window. Known limit.
- **Full file-state reconstruction.** I track which files each commit
  touches and flag values per symbol; I don't replay diffs into whole files.
  For pre-existing files the "before" state isn't in the data anyway.
- **Native Dutch generation.** Dutch derives from frozen English — trading
  some idiomatic nuance for the guarantee both languages say the same thing.
- **Deployment / web UI.** CLI + this README. The reviewer flow (restore,
  approval) would be the first thing to get a UI next.

Not cut, on purpose: the traceability validator and the ledger. They are the
direct answers to requirements 2 and 3.

## Repo layout

```
tempo_notes/
  history.py    load batches + parse diffs (files touched per commit, tags)
  scope.py      release window from git tags or version-marker subjects
  classify.py   commit kinds, noise lexicon, strict/flexible policy, reverts
  chains.py     union-find grouping by file collision
  flags.py      feature-flag value tracking from diffs
  entries.py    chain + window -> entry with status, evidence, cache key
  ledger.py     frozen decisions and wording, reuse by cache key
  generate.py   prompt, OpenRouter client, strict JSON parsing
  translate.py  EN->NL per entry, token-preservation invariant
  validate.py   independent post-generation checks
  render.py     the notes (md + html) for customers, review.html + review_report.md for the approver, traceability.json
  pipeline.py   orchestration of all of the above
tests/
  test_stories.py   every trap in the sample data, as a named regression test
data/
  commits.json, commits-followup.json, diffs/   the case materials.
  The tests read from this directory — keep it in place.
```
