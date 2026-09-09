"""The traps hidden in the sample data, as regression tests.

Run:  python3 -m pytest tests/ -q   (or python3 -m unittest discover tests)
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from tempo_notes.chains import build_chains
from tempo_notes.classify import Kind, classify, is_noise, policy_for
from tempo_notes.entries import Status, derive_entries
from tempo_notes.history import Commit, load_history
from tempo_notes.pipeline import run_pipeline
from tempo_notes.scope import ScopeError, resolve_window, window_for
from tempo_notes.translate import tokens_preserved

DATA = Path(__file__).resolve().parent.parent / "data"
INITIAL = [DATA / "commits.json"]
FULL = [DATA / "commits.json", DATA / "commits-followup.json"]


def fake_llm():
    """Test double for the LLM: mechanical but deterministic wording, so the
    pipeline around it (ledger, validation, rendering) is exercised for real.
    Lives here, not in the product — production has exactly one client."""
    import json as _json
    import re as _re
    _SKIP = ("(ci)", "poetry.lock", "tidy-up", "regenerate api client")

    def complete(system: str, user: str) -> str:
        if system.startswith("Translate"):
            return user  # identity translation keeps every token: valid Dutch stand-in
        subject = next(l[9:] for l in user.splitlines() if l.startswith("subject: "))
        low = subject.lower()
        if any(s in low for s in _SKIP):
            return _json.dumps({"publish": False, "skip_reason": "internal-only change",
                                "section": "changed", "breaking": False, "text_en": None})
        section = ("fixed" if low.startswith("fix") else
                   "improved" if low.startswith("perf") else "changed")
        text = _re.sub(r"^\w+(\([^)]*\))?!?: ", "", subject).strip().capitalize() + "."
        breaking = "BREAKING CHANGE" in user
        if breaking:
            text = ("The `db_url` environment variable is now `TEMPO_DATABASE__URL`; "
                    "update your environment before upgrading.")
        return _json.dumps({"publish": True, "skip_reason": None, "section": section,
                            "breaking": breaking, "text_en": text})

    return complete


def entries_for(commit_files):
    commits = load_history(commit_files, DATA / "diffs")
    window = window_for(commits, "2.1")
    return {e.chain_key: e for e in derive_entries(commits, build_chains(commits), window)}


class StoryTests(unittest.TestCase):
    def test_linear_candidate_then_retracted(self):
        """The revert arrives in a later batch and must invalidate the entry."""
        self.assertIs(entries_for(INITIAL)["0c7767228"].status, Status.CANDIDATE)
        after = entries_for(FULL)["0c7767228"]
        self.assertIs(after.status, Status.RETRACTED)
        self.assertEqual([c.sha for c in after.invalidators], ["576ca8a2d"])

    def test_dark_mode_cancels_inside_the_window(self):
        self.assertIs(entries_for(FULL)["33f3123ba"].status, Status.CANCELLED)

    def test_ical_gated_off_and_stable_across_batches(self):
        """Built in-window, flag off at the cut: never announced, key stable."""
        before, after = entries_for(INITIAL)["b43f10cdb"], entries_for(FULL)["b43f10cdb"]
        self.assertIs(before.status, Status.GATED_OFF)
        self.assertIs(after.status, Status.GATED_OFF)
        self.assertEqual(before.cache_key, after.cache_key)

    def test_billing_key_untouched_by_followup_fix(self):
        """A later ordinary fix continues the chain but must not reopen the entry."""
        self.assertEqual(entries_for(INITIAL)["8bd64ad0f"].cache_key,
                         entries_for(FULL)["8bd64ad0f"].cache_key)

    def test_breaking_change_survives_its_refactor_disguise(self):
        e = entries_for(FULL)["b6cb7554c"]
        self.assertIs(e.status, Status.CANDIDATE)  # refactor: subject, but publishable


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.out)

    def _run(self, commit_files):
        llm = fake_llm()
        return run_pipeline(commit_files, DATA / "diffs", "2.1", self.out,
                            llm, llm, verbose=False)

    def test_followup_only_removes_the_retracted_entry(self):
        self._run(INITIAL)
        page1 = (self.out / "release_notes_v2.1.0.en.md").read_text()
        summary = self._run(FULL)
        page2 = (self.out / "release_notes_v2.1.0.en.md").read_text()
        self.assertEqual(summary["generated"], 0)          # nothing re-worded
        removed = set(page1.splitlines()) - set(page2.splitlines())
        self.assertEqual(removed, {"- Sync projects from linear."})
        self.assertEqual(set(page2.splitlines()) - set(page1.splitlines()), set())

    def test_same_history_same_notes_byte_for_byte(self):
        self._run(FULL)
        page1 = (self.out / "release_notes_v2.1.0.en.md").read_text()
        self._run(FULL)
        self.assertEqual(page1, (self.out / "release_notes_v2.1.0.en.md").read_text())

    def test_window_without_diffs_warns_instead_of_silence(self):
        """The case materials only ship diffs for the 2.1 window + follow-up.
        Asking for an earlier release must produce a loud attention item, not
        silently empty notes — same failure mode as a wrong --diffs path."""
        summary = run_pipeline([DATA / "commits.json"], DATA / "diffs", "2.0.3",
                               self.out, fake_llm(), fake_llm(), verbose=False)
        self.assertEqual(summary["published"], 0)
        self.assertGreaterEqual(summary["attention"], 1)
        report = (self.out / "review_report.md").read_text(encoding="utf-8")
        self.assertIn("have no diff", report)


class ExplicitWindowTests(unittest.TestCase):
    """--from/--to: the operator's fallback for histories without markers."""

    def test_explicit_window_reproduces_the_marker_window(self):
        commits = load_history(FULL, DATA / "diffs")
        derived = window_for(commits, "2.1")
        explicit = resolve_window(commits, "2.1.0",
                                  start=derived.start_date, end=derived.end_date)
        self.assertEqual([c.sha for c in commits if derived.contains(c)],
                         [c.sha for c in commits if explicit.contains(c)])

    def test_bare_date_covers_the_whole_day(self):
        commits = load_history(FULL, DATA / "diffs")
        w = resolve_window(commits, "x", start="2026-02-23", end="2026-04-16")
        self.assertTrue(any(c.date.startswith("2026-04-16") and w.contains(c)
                            for c in commits))

    def test_from_without_to_fails_clearly(self):
        with self.assertRaises(ScopeError):
            resolve_window([], "x", start="2026-01-01")


def _commit(subject: str, sha: str = "0" * 9, body: str = "") -> Commit:
    return Commit(sha=sha, author="a", date="2026-01-01T00:00:00Z", subject=subject,
                  body=body, is_merge=False, diff=None)


class ClassificationTests(unittest.TestCase):
    """Noise (contentless) and unclassified (real but informal) are different
    things. Conflating them is how a history that doesn't use conventional
    commits publishes a blank page."""

    def test_contentless_subjects_are_noise(self):
        for subject in ("wip", "wip 2", "oops", "oops sorry", "asdf", "temp",
                        "debug", "cleanup", "formatting", "rebase", "fix typo",
                        "fix typo again", "run black over the codebase"):
            self.assertIs(classify(_commit(subject)), Kind.NOISE, subject)

    def test_informal_but_real_subjects_are_unclassified_not_noise(self):
        """These describe a change; the author was just terse. In a repo that
        doesn't use conventional commits, this is the entire history."""
        for subject in ("closes #412", "see ticket", "address review comments"):
            self.assertIs(classify(_commit(subject)), Kind.UNCLASSIFIED, subject)

    def test_junk_lexicon_is_anchored_to_the_whole_subject(self):
        """Regression guard on the lexicon itself: substring matching would
        swallow real work whose subject merely starts with a junk word."""
        for subject in ("fix typos in the invoice template shown to customers",
                        "cleanup of the export scheduler removes stale jobs",
                        "debug logging is no longer written to stdout"):
            self.assertIs(classify(_commit(subject)), Kind.UNCLASSIFIED, subject)
            self.assertFalse(is_noise(_commit(subject)), subject)

    def test_merges_and_reverts_are_neither(self):
        rev = _commit('Revert "feat(ui): dark mode toggle in settings"')
        self.assertIs(classify(rev), Kind.REVERT)
        merge = Commit(sha="m", author="a", date="2026-01-01T00:00:00Z",
                       subject="Merge pull request #470 from tempo/notifications",
                       body="", is_merge=True, diff=None)
        self.assertIs(classify(merge), Kind.MERGE)


class PolicyTests(unittest.TestCase):
    def test_strict_is_the_default(self):
        """Strict is what a repo using conventional commits wants, and it is
        what this repo's existing notes were produced under."""
        self.assertFalse(policy_for("strict").flexible)
        self.assertFalse(policy_for("anything-else").flexible)
        self.assertTrue(policy_for("flexible").flexible)

    def test_noise_is_excluded_under_both_policies(self):
        for mode in ("strict", "flexible"):
            self.assertTrue(policy_for(mode).excludes(_commit("wip")), mode)

    def test_only_flexible_keeps_informally_described_changes(self):
        """The failure this exists to prevent: a history that doesn't use
        conventional commits publishing a blank page."""
        self.assertTrue(policy_for("strict").excludes(_commit("closes #412")))
        self.assertFalse(policy_for("flexible").excludes(_commit("closes #412")))


class ClassificationRegressionTests(unittest.TestCase):
    """Splitting noise from unclassified must not move this history's notes:
    under strict the two are excluded together, exactly as before."""

    def test_strict_excludes_exactly_what_the_prefix_rule_excluded(self):
        commits = load_history(FULL, DATA / "diffs")
        prefix_rule = {c.sha for c in commits
                       if classify(c) in (Kind.NOISE, Kind.UNCLASSIFIED)}
        strict = {c.sha for c in commits if policy_for("strict").excludes(c)}
        self.assertEqual(prefix_rule, strict)

    def test_flexible_only_ever_adds_entries(self):
        commits = load_history(FULL, DATA / "diffs")
        window = window_for(commits, "2.1")

        def published(mode):
            policy = policy_for(mode)
            entries = derive_entries(commits, build_chains(commits, policy),
                                     window, policy)
            return {e.chain_key for e in entries if e.status is Status.CANDIDATE}

        self.assertLess(published("strict"), published("flexible"))


class TranslationInvariantTests(unittest.TestCase):
    def test_lost_identifier_is_detected(self):
        en = "The `db_url` variable is now `TEMPO_DATABASE__URL`."
        self.assertFalse(tokens_preserved(en, "De variabele heet nu anders."))
        self.assertTrue(tokens_preserved(en, "De variabele `db_url` heet nu `TEMPO_DATABASE__URL`."))

    def test_prose_acronyms_may_translate(self):
        """Regression: 'VAT' -> 'btw' rejected a valid Dutch translation (found
        in the first real run). Acronyms without underscores are prose."""
        en = "Fixed VAT calculation rounding for CSV invoice exports."
        self.assertTrue(tokens_preserved(en, "Btw-afronding bij csv-facturen opgelost."))
        self.assertFalse(tokens_preserved(
            "Rename FEATURE_ICAL_EXPORT before upgrading.",
            "Hernoem de exportvlag vóór het upgraden."))


if __name__ == "__main__":
    unittest.main()
