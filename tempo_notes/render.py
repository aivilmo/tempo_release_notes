"""Render the five outputs from the ledger. Pure formatting — every decision
was already made and recorded upstream, so rendering is trivially deterministic.

Two HTML views sit on top of the same frozen data, for two different
readers, and they are deliberately separate files rather than one page
trying to serve both:

- release_notes_v<V>.html — what Tempo's *customers* see. No mention of
  chains, ledgers, or decisions; just the notes, in the language they pick
  (a CSS-only toggle, no JS). This is the thing that gets linked from the
  public changelog.
- review.html — what the *approver* sees before publishing: the items that
  need a decision, a quiet log of everything the app decided on its own,
  and a preview of the public page framed unmistakably as a preview (inside
  a little browser-chrome box, with a link to the real thing) rather than
  being the page itself.

Both are single self-contained files (no JS beyond the CSS-only language
toggle, no network, no dependencies) that open with a double click.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

_SECTIONS = (("changed", "What's changed", "Wat is er veranderd"),
             ("improved", "What's improved", "Wat is er verbeterd"),
             ("fixed", "What's fixed", "Wat is er opgelost"))
_BANNER = {"en": "Before you upgrade — action required",
           "nl": "Vóór het upgraden — actie vereist"}


def _page(version: str, published: list[dict], lang: str) -> str:
    """Markdown notes, built on the same extraction as both HTML views —
    one source for what publishes, three renderings of it."""
    breaking, sections = _breaking_and_sections(published, lang)
    lines = [f"# Tempo {version}", ""]
    if breaking:
        # One banner, however many actions: self-hosted admins read it once,
        # everyone else scrolls past one block instead of several.
        lines += [f"> ⚠ **{_BANNER[lang]}**", ">"]
        lines += [f"> - {text}" for text in breaking]
        lines += [""]
    for title, texts in sections:
        lines += [f"## {title}", "", *[f"- {t}" for t in texts], ""]
    return "\n".join(lines)


def _review_report(version: str, run: int, groups: dict) -> str:
    L = [f"# Review report — Tempo {version}", ""]
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


def _esc(text: str) -> str:
    """Escape, then render `code spans` — commit bodies are untrusted input."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(text))


_TOKENS = """
/* royal-blue #6d4bee (+accent-light #8b6fff), turquoise #00c2b7,
   neutral-darkest #0d0a19, pampas paper family, 16px radius, borders at
   15% ink. Attention items use their beige scheme (pampas fill, royal-blue
   accent). The alert chip and the "needs your decision" items carry their
   flamingo-dark #c24838 — the one place the palette signals urgency, which
   is exactly why it never appears on the customer-facing page: nothing
   there is meant to alarm anyone. Headings follow the declared serif
   fallback (Newsreader -> Georgia); body follows the Inter stack. */
:root { --ink:#0d0a19; --muted:#5f5d5b; --paper:#fcf9f7; --card:#fdfcfc;
        --fill:#efe9e4; --line:#0d0a1926; --primary:#6d4bee;
        --primary-fill:#6d4bee14; --attn:#c24838; --attn-fill:#ff641d12;
        --grad:linear-gradient(90deg,#6d4bee,#8b6fff,#00c2b7);
        --radius:16px; }
"""

# review.html: internal, for the approver. Sans-serif machinery (badges,
# decision items, collapsible logs) wraps a boxed *preview* of the public
# page — never the public page's own markup, so the two can't be confused.
_CSS = _TOKENS + """
* { box-sizing:border-box }
body { margin:0; background:var(--paper); color:var(--ink);
       font:15px/1.55 Inter, -apple-system, "Segoe UI", sans-serif;
       -webkit-font-smoothing:antialiased; }
.brandbar { height:4px; background:var(--grad) }
main { max-width:1100px; margin:0 auto; padding:2.2rem 1.5rem 4rem }
.badge { display:inline-flex; align-items:center; gap:.4rem; margin:0 0 .7rem;
         padding:.25rem .7rem; border-radius:999px; background:var(--fill);
         color:var(--muted); font-size:.75rem; font-weight:600;
         letter-spacing:.03em; text-transform:uppercase }
.badge::before { content:"●"; color:var(--primary); font-size:.6rem }
h1 { font:600 1.8rem/1.2 "Newsreader 16 Pt", Georgia, serif; margin:0 }
.verdict { display:inline-block; margin:.8rem 0 1.2rem; padding:.35rem .9rem;
           border-radius:999px; background:var(--primary-fill);
           color:var(--primary); font-weight:600 }
.verdict.alert { background:var(--attn-fill); color:var(--attn) }
.public-link { display:inline-block; margin:0 0 2rem; color:var(--primary);
               font-weight:600; text-decoration:none; font-size:.9rem }
.public-link:hover { text-decoration:underline }
section > h2 { font-size:.95rem; font-weight:600; color:var(--muted);
               border-bottom:1px solid var(--line); padding-bottom:.4rem }
section > p.hint { color:var(--muted); font-size:.88rem; margin:.6rem 0 1rem; max-width:65ch }
.item { border:1px solid var(--line); border-left:4px solid var(--attn);
        background:var(--attn-fill); border-radius:var(--radius);
        padding:.9rem 1.1rem; margin:1rem 0; max-width:65ch }
.item h3 { margin:0 0 .3rem; font-size:1rem }
.item p { margin:.3rem 0; white-space:pre-line }
.pages { display:grid; grid-template-columns:1fr 1fr; gap:1.6rem; margin-top:1rem }
@media (max-width:800px) { .pages { grid-template-columns:1fr } }
.chrome-frame { background:var(--card); border:1px solid var(--line);
        border-radius:var(--radius); overflow:hidden;
        box-shadow:0 1px 2px #0d0a190d }
.chrome-bar { display:flex; align-items:center; gap:.9rem; padding:.55rem .9rem;
        background:var(--fill); border-bottom:1px solid var(--line) }
.chrome-dots { display:flex; gap:.3rem }
.chrome-dots span { width:.55rem; height:.55rem; border-radius:50%; background:#0d0a191f }
.chrome-url { font-size:.75rem; color:var(--muted); font-family:ui-monospace, Consolas, monospace }
.page { padding:1.4rem 1.8rem }
.page h3 { font:600 1.4rem/1.2 "Newsreader 16 Pt", Georgia, serif; margin:0 0 1rem }
.page h4 { font:600 1.05rem/1.3 "Newsreader 16 Pt", Georgia, serif;
           margin:1.4rem 0 .4rem; color:var(--primary) }
.page ul { margin:.2rem 0; padding-left:1.2rem }
.page li { margin:.35rem 0 }
.breaking { border:1px solid var(--line); border-left:4px solid var(--primary);
            background:var(--fill); border-radius:var(--radius);
            padding:.6rem 1rem; margin:0 0 1.2rem }
code { font-family:ui-monospace, Consolas, monospace; font-size:.92em;
       background:var(--primary-fill); color:var(--primary);
       padding:.05em .35em; border-radius:5px }
details { margin:.8rem 0; max-width:70ch }
summary { cursor:pointer; font-weight:600; color:var(--primary) }
details p { margin:.4rem 0 .4rem 1rem; color:var(--muted); white-space:pre-line }
footer { margin-top:2.5rem; border-top:1px solid var(--line); padding-top:1rem;
         color:var(--muted); max-width:70ch }
footer p { margin:.3rem 0 }
"""

# release_notes_v<V>.html: the actual public page. No decisions, no ledger,
# no reviewer language — just the notes, with a CSS-only EN/NL toggle so it
# stays a single dependency-free file, same as review.html.
_PUBLIC_CSS = _TOKENS + """
* { box-sizing:border-box }
body { margin:0; background:var(--paper); color:var(--ink);
       font:16px/1.65 Inter, -apple-system, "Segoe UI", sans-serif;
       -webkit-font-smoothing:antialiased; }
.brandbar { height:4px; background:var(--grad) }
main { max-width:720px; margin:0 auto; padding:3rem 1.5rem 5rem }
.sr-radio { position:absolute; opacity:0; width:0; height:0; pointer-events:none }
.hero { display:flex; align-items:flex-end; justify-content:space-between;
        gap:1rem; flex-wrap:wrap; border-bottom:1px solid var(--line);
        padding-bottom:1.4rem; margin-bottom:2rem }
.eyebrow { margin:0 0 .3rem; font-size:.8rem; font-weight:600; letter-spacing:.06em;
           text-transform:uppercase; color:var(--primary) }
h1 { margin:0; font:600 2.3rem/1.15 "Newsreader 16 Pt", Georgia, serif }
.switch { display:inline-flex; background:var(--fill); border-radius:999px; padding:3px }
.switch label { padding:.35rem 1.1rem; border-radius:999px; font-size:.85rem;
               font-weight:600; color:var(--muted); cursor:pointer; user-select:none }
#lang-en:checked ~ .hero .switch label[for="lang-en"],
#lang-nl:checked ~ .hero .switch label[for="lang-nl"] { background:var(--primary); color:#fff }
.lang-en, .lang-nl { display:none }
#lang-en:checked ~ .lang-en { display:block }
#lang-nl:checked ~ .lang-nl { display:block }
.breaking { border:1px solid var(--line); border-left:4px solid var(--primary);
            background:var(--fill); border-radius:var(--radius);
            padding:1rem 1.2rem; margin:0 0 2rem }
.breaking strong { display:block; margin-bottom:.5rem }
.breaking ul, h2 + ul { margin:.2rem 0; padding-left:1.3rem }
h2 { font:600 1.25rem/1.3 "Newsreader 16 Pt", Georgia, serif; margin:2.2rem 0 .6rem }
li { margin:.5rem 0 }
code { font-family:ui-monospace, Consolas, monospace; font-size:.9em;
       background:var(--primary-fill); color:var(--primary);
       padding:.05em .35em; border-radius:5px }
footer { margin-top:3rem; padding-top:1.4rem; border-top:1px solid var(--line);
         color:var(--muted); font-size:.85rem }
"""


def _breaking_and_sections(published: list[dict], lang: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """Shared extraction: the breaking-change lines and the three section
    lists, in one language. Both HTML views build on exactly this, so the
    approver's preview and the public page can never drift apart in content."""
    breaking = [r["decision"]["text_en"] if lang == "en" else
                (r.get("text_nl") or r["decision"]["text_en"])
                for r in published if r["decision"]["breaking"]]
    sections = []
    for key, title_en, title_nl in _SECTIONS:
        rows = [r for r in published
                if not r["decision"]["breaking"] and r["decision"]["section"] == key]
        if rows:
            texts = [r["decision"]["text_en"] if lang == "en" else
                     (r.get("text_nl") or r["decision"]["text_en"]) for r in rows]
            sections.append((title_en if lang == "en" else title_nl, texts))
    return breaking, sections


def _breaking_banner(breaking: list[str], lang: str) -> str:
    if not breaking:
        return ""
    items = "".join(f"<li>{_esc(t)}</li>" for t in breaking)
    return f'<div class="breaking"><strong>⚠ {_BANNER[lang]}</strong><ul>{items}</ul></div>'


def _html_page(version: str, published: list[dict], lang: str) -> str:
    """The notes rendered small, for the reviewer's side-by-side preview box."""
    breaking, sections = _breaking_and_sections(published, lang)
    out = [f"<h3>Tempo {_esc(version)}</h3>", _breaking_banner(breaking, lang)]
    for title, texts in sections:
        items = "".join(f"<li>{_esc(t)}</li>" for t in texts)
        out.append(f"<h4>{title}</h4><ul>{items}</ul>")
    return "".join(out)


def _public_sections(version: str, published: list[dict], lang: str) -> str:
    """The same notes, rendered as their own page — this is what ends up
    behind the public link, so headings start at h2 under the page's own h1."""
    breaking, sections = _breaking_and_sections(published, lang)
    out = [_breaking_banner(breaking, lang)]
    for title, texts in sections:
        items = "".join(f"<li>{_esc(t)}</li>" for t in texts)
        out.append(f"<h2>{title}</h2><ul>{items}</ul>")
    return "".join(out) or "<p>No customer-visible changes in this release.</p>"


def _public_html(version: str, published: list[dict]) -> str:
    """What Tempo's customers see. Deliberately knows nothing about chains,
    ledgers, or review status — if it isn't in `published`, it doesn't exist
    here. Language is a CSS-only toggle so this stays one static file."""
    body = (
        '<input class="sr-radio" type="radio" name="lang" id="lang-en" checked>'
        '<input class="sr-radio" type="radio" name="lang" id="lang-nl">'
        '<header class="hero"><div><p class="eyebrow">Release notes</p>'
        f'<h1>Tempo {_esc(version)}</h1></div>'
        '<div class="switch"><label for="lang-en">EN</label>'
        '<label for="lang-nl">NL</label></div></header>'
        f'<div class="lang-en" lang="en">{_public_sections(version, published, "en")}</div>'
        f'<div class="lang-nl" lang="nl">{_public_sections(version, published, "nl")}</div>'
        '<footer><p>Tempo — self-hosted time tracking.</p></footer>'
    )
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<title>Tempo {html.escape(version)} — release notes</title>"
            f"<style>{_PUBLIC_CSS}</style></head><body>"
            f"<div class='brandbar'></div><main>{body}</main></body></html>")


def _review_html(version: str, published: list[dict], groups: dict,
                 public_filename: str) -> str:
    """What the approver sees. Everything here is about the decision to
    publish, not the publishing itself — the preview of the public page sits
    inside a little browser-chrome box so it reads as a preview of another
    document, never as this one."""
    n = len(groups["attention"])
    verdict = (f'<p class="verdict alert">{n} item(s) need your decision</p>' if n
               else '<p class="verdict">Nothing needs your decision</p>')
    parts = ['<p class="badge">Internal review — not visible to customers</p>',
             f"<h1>Tempo {_esc(version)} release notes</h1>", verdict]
    if groups["attention"]:
        parts.append("<section><h2>Needs your decision</h2>")
        for it in groups["attention"]:
            parts.append(f'<div class="item"><h3>{_esc(it["title"])}</h3>'
                         f'<p>{_esc(it["detail"])}</p></div>')
        parts.append("</section>")
    parts.append(
        '<section><h2>Preview — what customers will see</h2>'
        '<p class="hint">Exactly the text that will publish, so you can approve without '
        f'reading the commit history. <a class="public-link" href="{html.escape(public_filename)}" '
        'target="_blank" rel="noopener">Open the public page instead →</a></p>'
        '<div class="pages">')
    for lang, url in (("en", "tempo.app/release-notes?lang=en"),
                      ("nl", "tempo.app/release-notes?lang=nl")):
        parts.append(
            '<div class="chrome-frame"><div class="chrome-bar">'
            '<div class="chrome-dots"><span></span><span></span><span></span></div>'
            f'<span class="chrome-url">{url}</span></div>'
            f'<div class="page">{_html_page(version, published, lang)}</div></div>')
    parts.append("</div></section>")
    quiet = [("Suppressed — no action expected", groups["suppressed"]),
             ("Informational", groups["info"])]
    parts.append("<section><h2>Decided by the app</h2>")
    for title, items in quiet:
        for it in items:
            parts.append(f"<details><summary>{title}: {_esc(it['title'])}</summary>"
                         f"<p>{_esc(it['detail'])}</p></details>")
    parts.append("</section><footer>")
    for line in groups["stability"]:
        parts.append(f"<p>{_esc(line)}</p>")
    parts.append("</footer>")
    body = "".join(parts)
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<title>Tempo {html.escape(version)} — review</title>"
            f"<style>{_CSS}</style></head><body>"
            f"<div class='brandbar'></div><main>{body}</main></body></html>")


def write_outputs(out_dir: Path, version: str, run: int,
                  published: list[dict], groups: dict,
                  ledger_records: dict) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    public_filename = f"release_notes_v{version}.html"
    files = {
        out_dir / f"release_notes_v{version}.en.md": _page(version, published, "en"),
        out_dir / f"release_notes_v{version}.nl.md": _page(version, published, "nl"),
        out_dir / public_filename: _public_html(version, published),
        out_dir / "review_report.md": _review_report(version, run, groups),
        out_dir / "review.html": _review_html(version, published, groups, public_filename),
        out_dir / "traceability.json": json.dumps(
            ledger_records, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    }
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
    return list(files)
