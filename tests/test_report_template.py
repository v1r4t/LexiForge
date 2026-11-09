"""Contract tests for the Keyterm Health report template.

The template in ``docs/keyterm-health-report-template.md`` and
``render_markdown`` must describe the same report. Drift in either direction
is the failure mode: a section the renderer emits but the template omits, or a
section the template promises but the renderer never writes. This module
renders a fixture through the real ``build_report`` + ``render_markdown`` path
and checks both directions against the template's machine-readable heading
list (``<!-- report-headings: ... -->``).

No significance test belongs in the report; only the pre-registered
non-inferiority rule decides the verdict.
"""

from __future__ import annotations

import re
from pathlib import Path

from lexiforge.report.keyterm_health import build_report, render_markdown

TEMPLATE = Path(__file__).resolve().parents[1] / "docs" / "keyterm-health-report-template.md"

_HEADING_RE = re.compile(r"^#{2,3}\s+(?:\d+\.\s*)?(.+?)\s*$", re.MULTILINE)
_MARKER_RE = re.compile(r"<!--\s*report-headings:\s*(.+?)\s*-->", re.DOTALL)
_SAMPLE_RE = re.compile(r"```markdown\n(.*?)```", re.DOTALL)

# Sections a dependency may add before the template is revised. They are
# filtered from the exact comparison but must still be named in the template
# prose, so a silently-added section is still a test failure. Kept normalised
# because headings are compared after `_norm`.
OPTIONAL_HEADINGS = {"endpoints (a/b)"}

PROVENANCE_FIELDS = (
    # (name used in the template, label the renderer prints)
    ("CANON_VERSION", "canon version"),
    ("context hash", "context hash"),
    ("seed", "seed"),
    ("audio hash", "audio hash"),
    ("chain", "audio chain"),
    ("date", "date"),
)


def _norm(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def _template_text() -> str:
    assert TEMPLATE.exists(), f"missing report template: {TEMPLATE}"
    return TEMPLATE.read_text(encoding="utf-8")


def _headings(markdown: str) -> list[str]:
    return [_norm(match) for match in _HEADING_RE.findall(markdown)]


def _declared_headings(template: str) -> list[str]:
    matches = _MARKER_RE.findall(template)
    assert len(matches) == 1, "template needs exactly one report-headings marker"
    return [_norm(part) for part in matches[0].split("|") if part.strip()]


def _fixture_report() -> dict:
    """A small two-arm, four-call report with finite paired deltas.

    Baseline recall 7/10 and selected recall 9/10 on every call make all four
    paired deltas +0.20, so the fixture reaches a decidable PASS rather than a
    wide CI. The selected arm also carries term-level rows so the appendix is
    populated.
    """
    baseline_metrics = {
        "real_recall": {"num": 28, "den": 40},
        "fictional_recall": {"num": 2, "den": 4},
        "oov_recall": {"num": 0, "den": 2},
        "wer": 0.08,
        "decoder_ignore": {"num": 4, "den": 40},
    }
    selected_metrics = {
        "real_recall": {"num": 36, "den": 40},
        "fictional_recall": {"num": 3, "den": 4},
        "oov_recall": {"num": 1, "den": 2},
        "wer": 0.07,
        "decoder_ignore": {"num": 2, "den": 40},
    }
    baseline_rows = [
        {
            "call_id": f"c0{index}",
            "real_recall": {"num": 7, "den": 10},
            "insertions_per_utterance": {"total_events": 0, "n_utterances": 10},
        }
        for index in range(4)
    ]
    selected_rows = [
        {
            "call_id": f"c0{index}",
            "real_recall": {"num": 9, "den": 10},
            "insertions_per_utterance": {"total_events": 2, "n_utterances": 10},
        }
        for index in range(4)
    ]
    selected_rows.extend(
        [
            {"call_id": "c00", "term_id": "T1", "origin": "real", "hit": True},
            {"call_id": "c01", "term_id": "T2", "origin": "real", "hit": False},
            {
                "call_id": "c02",
                "term_id": "T3",
                "origin": "real",
                "hit": True,
                "insertion": True,
            },
            {"call_id": "c00", "term_id": "F1", "origin": "fictional", "hit": True},
            {"call_id": "c01", "term_id": "F2", "origin": "fictional", "hit": False},
            {"call_id": "c02", "term_id": "O1", "origin": "oov", "hit": False},
        ]
    )

    provenance = {
        "model": "prisma-v3.0",
        "canon_version": "3.1.0",
        "context_hash": "a1b2c3d4e5f6a7b8c9d0",
        "seed": 0,
        "audio_hash": "sha256:0011223344556677",
        "audio_chain": "16k -> 8k -> G.711 -> 8k",
        "date": "2026-11-09",
    }
    prereg = {
        "recall_margin": -0.05,
        "insertion_cap": 0.5,
        "cluster_key": "call_id",
        "seed": 0,
        "n_boot": 2000,
    }
    arms = [
        {"name": "baseline", "metrics": baseline_metrics, "rows": baseline_rows},
        {"name": "selected-200", "metrics": selected_metrics, "rows": selected_rows},
    ]
    return build_report(
        call_id="c00",
        arms=arms,
        provenance=provenance,
        prereg=prereg,
    )


def test_template_and_renderer_agree_on_headings() -> None:
    template = _template_text()
    rendered = render_markdown(_fixture_report())

    declared = _declared_headings(template)
    emitted = [heading for heading in _headings(rendered) if heading not in OPTIONAL_HEADINGS]

    assert declared, "the report-headings marker is empty"
    # Both directions at once: identical order and content.
    assert declared == emitted

    for heading in OPTIONAL_HEADINGS:
        assert heading in _norm(template), f"optional heading {heading!r} is undocumented"


def test_required_fields_are_named_and_filled() -> None:
    template = _template_text()
    rendered = render_markdown(_fixture_report())
    template_low = _norm(template)
    rendered_low = _norm(rendered)

    for template_label, rendered_label in PROVENANCE_FIELDS:
        assert _norm(template_label) in template_low, (
            f"template omits provenance field {template_label!r}"
        )
        assert (
            _norm(rendered_label) in rendered_low or _norm(template_label) in rendered_low
        ), f"rendered report omits provenance field {rendered_label!r}"

    # Filled, not a blank skeleton: the fixture's actual stamps are rendered.
    for value in ("prisma-v3.0", "3.1.0", "a1b2c3d4e5f6a7b8c9d0", "2026-11-09"):
        assert value in rendered, f"rendered report is missing fixture value {value!r}"

    for token in ("real", "fictional", "oov"):
        assert token in template_low
        assert token in rendered_low, f"term appendix omits {token!r}"

    for token in ("95% ci", "verified", "inferred", "unverified", "synthetic", "circularity"):
        assert token in template_low, f"template omits {token!r}"
        assert token in rendered_low, f"rendered report omits {token!r}"

    for token in ("PASS", "FAIL", "INCONCLUSIVE"):
        assert token in template, f"template omits verdict token {token!r}"

    assert "PASS" in rendered
    assert "descriptive lift" in template_low
    assert "estimate" in template_low


def test_rendered_report_has_no_significance_test() -> None:
    rendered = render_markdown(_fixture_report())
    rendered_low = rendered.lower()

    assert "p-value" not in rendered_low
    assert "p value" not in rendered_low
    assert re.search(r"\bp\s*[=<>]", rendered_low) is None

    # The template itself must not hold a stray significance field either.
    template_low = _template_text().lower()
    assert "p-value" not in template_low
    assert "p value" not in template_low


def test_filled_sample_is_complete_and_headed_like_the_renderer() -> None:
    template = _template_text()
    samples = _SAMPLE_RE.findall(template)
    assert len(samples) == 1, "template needs exactly one fenced markdown sample"

    sample = samples[0]
    assert "# Keyterm Health Report - c00" in sample
    sample_headings = [heading for heading in _headings(sample) if heading not in OPTIONAL_HEADINGS]
    assert sample_headings == _declared_headings(template)

    for token in ("PASS", "| baseline |", "95% CI", "Verified", "Circularity"):
        assert token in sample, f"filled sample omits {token!r}"
    assert "| n/a |" not in sample, "filled sample must show real values, not placeholders"
