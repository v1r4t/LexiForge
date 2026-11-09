"""Tests for the static Keyterm Health report page (P22).

The page is a single self-contained HTML file rendered from the report's
Markdown. It must stay static: no scripts, no CDN, and no external requests.
"""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from build_report_page import build_page, main  # noqa: E402

SECTIONS = (
    "Provenance",
    "Results per arm",
    "Term-level appendix",
    "Verdict",
    "Descriptive lift",
    "Claims register",
    "Synthetic-audio and circularity disclosure",
)


class _Headings(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.h1: list[str] = []
        self.h2: list[str] = []
        self._current: list[str] | None = None
        self._tag = ""

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        if tag in ("h1", "h2"):
            self._tag = tag
            self._current = []

    def handle_endtag(self, tag: str) -> None:
        if tag == self._tag and self._current is not None:
            text = "".join(self._current).strip()
            (self.h1 if tag == "h1" else self.h2).append(text)
            self._current = None
            self._tag = ""

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current.append(data)


def _sample_report(**overrides: object) -> dict:
    """A self-contained fixture: no dependency on P11 or P17 modules."""
    report: dict = {
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
            "canon_version": "matcher-v1.0",
            "context_hash": "9f86d081884c7d659a2feaa0c55ad015",
            "seed": 0,
            "audio_hash": "e3b0c44298fc1c149afbf4c8996fb924",
            "audio_chain": "16 kHz -> 8 kHz -> G.711 -> decode",
            "date": "2026-11-09",
        },
        "arms": [],
        "metrics_summary": [
            {
                "arm": "baseline",
                "real_recall": {"num": 8, "den": 10, "rate": 0.8},
                "fictional_recall": {"num": 1, "den": 2, "rate": 0.5},
                "oov_recall": {"num": 0, "den": 1, "rate": 0.0},
                "insertions_per_utterance": {"num": 1, "den": 4, "rate": 0.25},
                "wer": {"rate": 0.12},
                "decoder_ignore": {"num": 2, "den": 10, "rate": 0.2},
            },
            {
                "arm": "selected-200",
                "real_recall": {"num": 9, "den": 10, "rate": 0.9},
                "fictional_recall": {"num": 2, "den": 2, "rate": 1.0},
                "oov_recall": {"num": 1, "den": 1, "rate": 1.0},
                "insertions_per_utterance": {"num": 2, "den": 4, "rate": 0.5},
                "wer": {"rate": 0.11},
                "decoder_ignore": {"num": 1, "den": 10, "rate": 0.1},
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
    report.update(overrides)
    return report


def test_build_page_writes_parseable_html_and_returns_path(tmp_path: Path) -> None:
    out = tmp_path / "report" / "index.html"
    result = build_page(_sample_report(), out)

    assert result == out
    html = out.read_text(encoding="utf-8")
    assert html.lstrip().lower().startswith("<!doctype html>")
    _Headings().feed(html)  # raises on malformed markup


def test_sample_banner_is_amber_and_explicit(tmp_path: Path) -> None:
    html = build_page(_sample_report(), tmp_path / "index.html").read_text(encoding="utf-8")

    assert "Illustrative sample data" in html
    assert "not results" in html
    assert 'id="sample-banner"' in html
    assert "role=\"alert\"" in html
    # Amber surface, border, and text.
    assert "#fffbeb" in html
    assert "#f59e0b" in html
    assert "#78350f" in html


def test_banner_is_absent_for_measured_reports(tmp_path: Path) -> None:
    report = _sample_report(is_sample=False)
    html = build_page(report, tmp_path / "index.html").read_text(encoding="utf-8")

    assert "Illustrative sample data" not in html
    assert "sample-banner" not in html
    assert "role=\"alert\"" not in html


def test_provenance_data_source_also_marks_a_sample(tmp_path: Path) -> None:
    report = _sample_report()
    report.pop("is_sample")
    report["provenance"] = dict(report["provenance"], data_source="illustrative_sample")
    html = build_page(report, tmp_path / "index.html").read_text(encoding="utf-8")

    assert "Illustrative sample data" in html


def test_page_makes_no_external_requests(tmp_path: Path) -> None:
    html = build_page(_sample_report(), tmp_path / "index.html").read_text(encoding="utf-8")
    lowered = html.lower()

    assert "http://" not in lowered
    assert "https://" not in lowered
    assert "<script" not in lowered
    assert "src=" not in lowered
    assert "url(" not in lowered
    assert "@import" not in lowered


def test_external_markdown_links_are_not_emitted(tmp_path: Path) -> None:
    report = _sample_report(
        disclosures={
            "synthetic_audio": "See [the dashboard](https://example.org/dashboard).",
            "circularity": "Terms come from pass 1, never the reference.",
        }
    )
    html = build_page(report, tmp_path / "index.html").read_text(encoding="utf-8")

    assert "https://" not in html
    assert "example.org" not in html
    assert '<a href="https' not in html


def test_seven_section_headings_are_rendered(tmp_path: Path) -> None:
    html = build_page(_sample_report(), tmp_path / "index.html").read_text(encoding="utf-8")
    headings = _Headings()
    headings.feed(html)

    assert len(headings.h1) == 1
    assert "Keyterm Health Report" in headings.h1[0]
    assert len(headings.h2) == 7
    for section, heading in zip(SECTIONS, headings.h2):
        assert section in heading


def test_example_text_passes_privacy_redaction(tmp_path: Path) -> None:
    report = _sample_report(
        verdict_reason=(
            "Sample note: caller 9876543210 and sample@example.org were used for layout."
        )
    )
    html = build_page(report, tmp_path / "index.html").read_text(encoding="utf-8")

    assert "9876543210" not in html
    assert "sample@example.org" not in html
    assert "[PHONE]" in html
    assert "[EMAIL]" in html


def test_call_id_is_html_escaped(tmp_path: Path) -> None:
    html = build_page(
        _sample_report(call_id="<script>alert(1)</script>"),
        tmp_path / "index.html",
    ).read_text(encoding="utf-8")

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_cli_builds_the_committed_sample_page(tmp_path: Path) -> None:
    out = tmp_path / "sample" / "index.html"
    assert main(["--sample", "--out", str(out)]) == 0

    html = out.read_text(encoding="utf-8")
    assert "Illustrative sample data" in html
    headings = _Headings()
    headings.feed(html)
    assert len(headings.h2) == 7


def test_committed_sample_page_exists_and_is_static() -> None:
    page = REPO_ROOT / "web" / "data" / "report" / "sample" / "index.html"
    assert page.exists()
    html = page.read_text(encoding="utf-8")
    lowered = html.lower()
    assert "Illustrative sample data" in html
    assert "http://" not in lowered
    assert "https://" not in lowered
    assert "<script" not in lowered
    headings = _Headings()
    headings.feed(html)
    assert len(headings.h2) == 7
