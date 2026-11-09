#!/usr/bin/env python3
"""Build the static Keyterm Health report page.

The report is authored as Markdown by
:func:`lexiforge.report.keyterm_health.render_markdown`; this script wraps that
Markdown in one self-contained HTML file with embedded CSS. There is no
JavaScript, no CDN, and no external asset, so the page can be opened offline or
served by any static host.

Samples are labelled with the same amber banner string as the dashboard: a
reader must never mistake illustrative numbers for measured results. Report
text is passed through :func:`lexiforge.privacy.redact_text` before rendering.

Usage::

    python scripts/build_report_page.py --report runs/study/report.json \
        --out web/data/report/index.html
    python scripts/build_report_page.py --sample \
        --out web/data/report/sample/index.html
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lexiforge.canon import CANON_VERSION  # noqa: E402
from lexiforge.privacy import redact_text  # noqa: E402

__all__ = ["build_page", "markdown_to_html"]

SAMPLE_BANNER_TEXT = "Illustrative sample data \u2014 not results."

_BANNER_STYLE = (
    "background:#fffbeb;border:1px solid #f59e0b;border-left:6px solid #d97706;"
    "border-radius:6px;color:#78350f;margin:0 0 1.5rem;padding:0.9rem 1.1rem;"
)

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_TABLE_SEPARATOR = re.compile(r"^:?-{3,}:?$")
_CODE_SPAN = re.compile(r"(`[^`]+`)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_SAFE_HREF = re.compile(r"^(?:#|/|\./|\.\./)")

_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0;
  background: #f8fafc;
  color: #0f172a;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
  line-height: 1.55;
}
.page { max-width: 72rem; margin: 0 auto; padding: 2rem 1.25rem 3rem; }
main.report {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
  padding: 2rem;
}
h1 { margin: 0 0 1rem; font-size: 1.7rem; line-height: 1.25; }
h2 {
  margin: 2rem 0 0.75rem;
  padding-bottom: 0.35rem;
  border-bottom: 1px solid #e2e8f0;
  font-size: 1.2rem;
}
h3 { margin: 1.4rem 0 0.5rem; font-size: 1.02rem; }
p { margin: 0.5rem 0 0.9rem; }
.table-wrap { margin: 0.75rem 0 1rem; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
th, td { border: 1px solid #e2e8f0; padding: 0.45rem 0.6rem; text-align: left; vertical-align: top; }
th { background: #f1f5f9; font-weight: 600; }
code {
  background: #f1f5f9;
  border-radius: 3px;
  padding: 0.1rem 0.3rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.9em;
}
ul { margin: 0.5rem 0 1rem 1.25rem; padding: 0; }
li { margin: 0.2rem 0; }
footer {
  margin-top: 1.25rem;
  color: #64748b;
  font-size: 0.8rem;
  text-align: center;
}
@media print {
  body { background: #ffffff; }
  .page { max-width: none; padding: 0; }
  main.report { border: 0; box-shadow: none; padding: 0; }
}
""".strip()


def _inline(text: str) -> str:
    """Render the inline Markdown used by the report (bold, code, links)."""
    escaped = html.escape(text, quote=True)
    pieces = _CODE_SPAN.split(escaped)
    rendered: list[str] = []
    for index, piece in enumerate(pieces):
        if index % 2 == 1 and piece.startswith("`") and piece.endswith("`"):
            rendered.append(f"<code>{piece[1:-1]}</code>")
            continue
        rendered.append(_link(_BOLD.sub(r"<strong>\1</strong>", piece)))
    return "".join(rendered)


def _link(text: str) -> str:
    """Keep relative links only; drop any external target to preserve zero requests."""

    def replace(match: re.Match[str]) -> str:
        label, href = match.group(1), match.group(2)
        if _SAFE_HREF.match(href):
            return f'<a href="{href}">{label}</a>'
        return label

    return _LINK.sub(replace, text)


def _split_row(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip() for cell in body.split("|")]


def _is_separator(line: str) -> bool:
    cells = _split_row(line)
    return bool(cells) and all(_TABLE_SEPARATOR.match(cell) for cell in cells)


def _table(block: list[str]) -> str:
    header = _split_row(block[0])
    rows = block[1:]
    if rows and _is_separator(rows[0]):
        rows = rows[1:]

    out = ['<div class="table-wrap"><table>', "<thead><tr>"]
    out.extend(f"<th>{_inline(cell)}</th>" for cell in header)
    out.append("</tr></thead>")
    if rows:
        out.append("<tbody>")
        for row in rows:
            cells = _split_row(row)
            cells = (cells + [""] * len(header))[: len(header)]
            out.append(
                "<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in cells) + "</tr>"
            )
        out.append("</tbody>")
    out.append("</table></div>")
    return "".join(out)


def markdown_to_html(markdown: str) -> str:
    """Convert the report's Markdown subset to HTML.

    Supported: headings, pipe tables, bullet lists, paragraphs, bold, inline
    code, and relative links. Everything is HTML-escaped first.
    """
    lines = markdown.splitlines()
    out: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            out.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            flush()
            index += 1
            continue

        heading = _HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            index += 1
            continue

        if line.startswith("|"):
            flush()
            block: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                block.append(lines[index].strip())
                index += 1
            out.append(_table(block))
            continue

        if line.startswith("- "):
            flush()
            items: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("- "):
                items.append(lines[index].strip()[2:].strip())
                index += 1
            out.append("<ul>" + "".join(f"<li>{_inline(item)}</li>" for item in items) + "</ul>")
            continue

        paragraph.append(line)
        index += 1

    flush()
    return "\n".join(out)


def _is_sample(report: Mapping[str, Any]) -> bool:
    if report.get("is_sample") is True:
        return True
    if report.get("data_source") == "illustrative_sample":
        return True
    for key in ("provenance", "meta", "config"):
        block = report.get(key)
        if not isinstance(block, Mapping):
            continue
        if block.get("is_sample") is True:
            return True
        if block.get("data_source") == "illustrative_sample":
            return True
    return False


def _banner() -> str:
    return (
        '<div id="sample-banner" class="sample-banner amber" role="alert" '
        f'style="{_BANNER_STYLE}">'
        f"<strong>{html.escape(SAMPLE_BANNER_TEXT)}</strong> "
        "Every number and example here is hand-written to exercise the layout. "
        "Run <code>lexiforge export-web</code> and rebuild this page from scored "
        "output before quoting any figure."
        "</div>"
    )


def _count(num: float, den: float) -> dict:
    return {"num": num, "den": den, "rate": num / den if den else 0.0}


def _sample_report() -> dict:
    """Hand-written illustrative report: no measured result is implied."""
    return {
        "call_id": "c00",
        "is_sample": True,
        "n_calls": 4,
        "prereg": {
            "recall_margin": -0.05,
            "insertion_cap": 0.5,
            "seed": 0,
            "cluster_key": "call_id",
        },
        "provenance": {
            "model": "gnani-prisma-v3.0",
            "canon_version": CANON_VERSION,
            "context_hash": "9f86d081884c7d659a2feaa0c55ad015",
            "seed": 0,
            "audio_hash": "e3b0c44298fc1c149afbf4c8996fb924",
            "audio_chain": "16 kHz -> 8 kHz -> G.711 -> decode",
            "date": "2026-11-09",
        },
        "metrics_summary": [
            {
                "arm": "baseline",
                "real_recall": _count(8, 10),
                "fictional_recall": _count(1, 2),
                "oov_recall": _count(0, 1),
                "insertions_per_utterance": _count(1, 4),
                "wer": {"rate": 0.12},
                "decoder_ignore": _count(2, 10),
            },
            {
                "arm": "selected-200",
                "real_recall": _count(9, 10),
                "fictional_recall": _count(2, 2),
                "oov_recall": _count(1, 1),
                "insertions_per_utterance": _count(2, 4),
                "wer": {"rate": 0.11},
                "decoder_ignore": _count(1, 10),
            },
            {
                "arm": "mismatched-200",
                "real_recall": _count(6, 10),
                "fictional_recall": _count(0, 2),
                "oov_recall": _count(0, 1),
                "insertions_per_utterance": _count(3, 4),
                "wer": {"rate": 0.16},
                "decoder_ignore": _count(3, 10),
            },
        ],
        "paired_deltas": {
            "real_recall": {
                "comparison": "selected-200 vs baseline",
                "mean": 0.1,
                "ci_low": -0.02,
                "ci_high": 0.22,
                "n": 4,
                "deltas": [0.1, 0.0, 0.2, 0.1],
            },
            "insertions_per_utterance": {
                "comparison": "selected-200 vs baseline",
                "mean": 0.25,
                "ci_low": -0.1,
                "ci_high": 0.6,
                "n": 4,
                "deltas": [0.0, 0.5, 0.0, 0.5],
            },
        },
        "term_level": {
            "arm": "selected-200",
            "real": {"recovered": 9, "lost": 1, "inserted": 2},
            "fictional": {"recovered": 2, "lost": 0, "inserted": 0},
            "oov": {"recovered": 1, "lost": 0, "inserted": 0},
        },
        "lift": {
            "metric": "real_recall",
            "estimate": 0.1,
            "ci_low": -0.02,
            "ci_high": 0.22,
            "claimable": False,
        },
        "claims_register": {
            "verified": ["Four paired calls were scored."],
            "inferred": ["The selector may help real terms."],
            "unverified": ["No real customer audio exists."],
        },
        "verdict": "INCONCLUSIVE",
        "verdict_reason": "Four paired calls cannot decide the non-inferiority rule.",
    }


def build_page(report: Mapping[str, Any], out_path: str | Path) -> Path:
    """Render ``report`` to a single static HTML page and return its path."""
    if not isinstance(report, Mapping):
        raise TypeError("report must be a mapping")

    # Lazy import: the report module may be absent in a partial checkout.
    from lexiforge.report.keyterm_health import render_markdown

    markdown = render_markdown(dict(report))
    markdown, _ = redact_text(markdown)
    body = markdown_to_html(markdown)

    raw_call_id = str(report.get("call_id") or "unknown")
    call_id, _ = redact_text(raw_call_id)
    title = f"Keyterm Health Report - {html.escape(call_id, quote=True)}"

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{title}</title>",
        "<style>",
        _CSS,
        "</style>",
        "</head>",
        "<body>",
        '<div class="page">',
    ]
    if _is_sample(report):
        parts.append(_banner())
    parts.extend(
        [
            '<main class="report">',
            body,
            "</main>",
            "<footer>Static report page. No scripts and no external assets.</footer>",
            "</div>",
            "</body>",
            "</html>",
            "",
        ]
    )

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def _load_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the static Keyterm Health report page.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--report", type=Path, help="report JSON written by the study runner")
    source.add_argument("--sample", action="store_true", help="build the bundled illustrative page")
    parser.add_argument("--out", type=Path, required=True, help="output index.html path")
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = _sample_report() if args.sample else _load_report(args.report)
    build_page(report, args.out)
    print("wrote report page")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
