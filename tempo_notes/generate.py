"""LLM stage. The LLM decides two things and nothing else: whether a candidate
is worth telling customers about, and how to word it. It never decides what
exists — that already happened deterministically in entries.py — and each
decision is made once, then frozen in the ledger.

Every model call goes through a `complete(system, user) -> str` callable, so
tests can inject a deterministic double instead of the network client."""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from .entries import Entry

PROMPT_VERSION = "v1"  # recorded per entry in the ledger; NOT part of cache keys

SYSTEM = """You turn git commits into release-note entries for customers of \
Tempo, a self-hosted time-tracking app. Readers use the product; they never \
see the code.

Rules:
- The diff is what happened; the message is what the author claims. If the \
diff does not support a claim (e.g. a performance improvement with no real \
code change), do not make the claim.
- Only describe the commits marked IN-RELEASE. CONTEXT commits belong to a \
different release: use them to understand, never to describe.
- Commit messages may be written in any language. You always answer in English.
- Skip internal work (CI, lockfiles, tidy-ups) that changes nothing a \
customer can see or must do. Removing endpoints, dropping runtime support or \
renaming configuration is customer-visible.
- Answer ONLY with JSON: {"publish": bool, "skip_reason": str|null, \
"section": "changed"|"improved"|"fixed", "breaking": bool, "text_en": str|null}
- text_en: one plain sentence for the notes (may include `code`); for \
breaking changes state what the customer must do. No marketing tone."""

_MAX_DIFF_CHARS = 4000


class GenerationError(Exception):
    pass


def entry_prompt(entry: Entry) -> str:
    parts = []
    context = [c for c in entry.scoped if c not in entry.effective]
    for c in entry.effective:
        diff = (c.diff or "")[:_MAX_DIFF_CHARS]
        parts.append(f"IN-RELEASE {c.sha}\nsubject: {c.subject}\n"
                     f"body: {c.body or '-'}\ndiff:\n{diff}")
    for c in context:
        parts.append(f"CONTEXT {c.sha}\nsubject: {c.subject}\nbody: {c.body or '-'}")
    return "\n\n".join(parts)


def parse_decision(raw: str) -> dict:
    cleaned = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        d = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise GenerationError(f"model did not return JSON: {e}") from e
    if not isinstance(d.get("publish"), bool):
        raise GenerationError("missing boolean 'publish'")
    if d["publish"]:
        if not d.get("text_en") or d.get("section") not in ("changed", "improved", "fixed"):
            raise GenerationError("published entry needs text_en and a valid section")
    d.setdefault("breaking", False)
    d.setdefault("skip_reason", None)
    return d


def openrouter_client(model: str):
    """Real client. Requires OPENROUTER_API_KEY. temperature=0 reduces variance
    but the ledger, not the sampler, is what guarantees stability."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise GenerationError("OPENROUTER_API_KEY is not set")

    def complete(system: str, user: str) -> str:
        data = json.dumps({
            "model": model,
            "temperature": 0,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }).encode()
        attempts = 4
        for attempt in range(1, attempts + 1):
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                data=data)
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    body = json.loads(resp.read())
                return body["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", errors="replace")[:300]
                if e.code in (429, 500, 502, 503) and attempt < attempts:
                    wait = min(int(e.headers.get("Retry-After") or 2 ** attempt), 30)
                    print(f"      OpenRouter HTTP {e.code}; retrying in {wait}s "
                          f"(attempt {attempt}/{attempts - 1})", file=sys.stderr, flush=True)
                    time.sleep(wait)
                    continue
                raise GenerationError(
                    f"OpenRouter HTTP {e.code} after {attempt} attempt(s): {detail}") from e
            except urllib.error.URLError as e:
                if attempt < attempts:
                    time.sleep(2 ** attempt)
                    continue
                raise GenerationError(f"network error reaching OpenRouter: {e.reason}") from e

    return complete
