# Keyterm Health Report Template

**Internal harness validation - not for external distribution.**

This document is the readable contract for the Keyterm Health Report emitted by
`lexiforge.report.keyterm_health.build_report()` and `render_markdown()`. Both
directions are machine-checked in `tests/test_report_template.py`: every heading
the renderer emits must be named here, and every heading this template promises
must appear in a rendered fixture. Adding, renaming, dropping or reordering a
section in one place without the other fails the test.

<!-- report-headings: Provenance | Results per arm | Paired deltas (95% CI) | Term-level appendix | Verdict | Descriptive lift (secondary) | Claims register | Verified | Inferred | Unverified | Synthetic-audio and circularity disclosure | Synthetic audio | Circularity -->

The marker above is the single machine-readable list of rendered headings, in
renderer order. The A/B endpoint work adds an optional `### Endpoints (A/B)`
subsection directly after "Paired deltas (95% CI)"; it is a subsection, not an
eighth section, and the marker gains it when that work lands.

## How to produce a report

```python
from lexiforge.report.keyterm_health import build_report, render_markdown

report = build_report(
    call_id="c00",
    arms=arms,                # baseline + every compared arm, same audio/model/format
    provenance=provenance,    # see section 1
    prereg=prereg,            # recall_margin, insertion_cap, cluster_key, seed, n_boot
)
markdown = render_markdown(report)
```

- `provenance` is a mapping; `lexiforge.report.provenance.provenance_block()`
  is the canonical producer when that module is available.
- `claims_register` is populated from the verified/inferred/unverified
  register, never typed by hand in the Markdown.
- The scraped report is written once per call or per study. Nothing in it is
  edited after the fact; a correction is a new dated report.

## 1. Provenance

Every report opens with a two-column table. A recall figure without this stamp
is not reportable.

| Field | Provenance key | Rule |
|---|---|---|
| Model | `model` | Exact model identity and version (for example `prisma-v3.0`). |
| `CANON_VERSION` | `canon_version` | Canonicaliser version, defaulting to `lexiforge.canon.CANON_VERSION`; required. |
| Context hash | `context_hash` | sha256 of the exact keyterm list sent to the API, hashed as bytes, never a file path. |
| Seed | `seed` | The selection/permutation seed used for this run. |
| Audio hash | `audio_hash` | sha256 of the audio bytes actually sent. |
| Audio-processing chain | `audio_chain` | Ordered steps applied to the audio (for example `16k -> 8k -> G.711 -> 8k`). |
| Date | `date` | ISO-8601 date of the run or report. |

Optional provenance keys are rendered after the required ones: `format`,
`language_code`, `study_id`, `generated_at`. Missing required provenance makes
the report non-reportable; never substitute "unknown" for a missing stamp.

## 2. Results per arm

One row per arm. Every arm in a comparison must share audio, model, format,
language and budget; only the keyterm list may differ.

| Column | Content |
|---|---|
| Arm | Arm name, including the exact budget suffix (`baseline`, `selected-200`, `mismatched-200`, `hard-negative-200`). |
| Real recall | Real-term hits / real-term opportunities, with the percentage. |
| Fictional recall | Fictional-term hits / fictional-term opportunities. |
| OOV recall | Out-of-vocabulary hits / OOV opportunities. |
| Insertions / utterance | Total glossary insertions / utterances, shown as `num/den = mean`. |
| WER | Word error rate as a guardrail. |
| Decoder ignore | Spoken context terms still missed / spoken context terms, with the denominator spelled out below the table. |

Zero-denominator cells render `n/a` rather than `0%`. A short arm is never
compared as if it were equal-budget.

### Paired deltas (95% CI)

Paired, cluster-level differences for the pre-registered pair; the display
default is `baseline` versus the selected arm. One value per call, delta is
`arm_b - arm_a`, and the interval resamples whole calls. Columns: Comparison,
Metric, Delta, 95% CI, Calls (the observed paired count, never the planned n).

- Baseline-versus-`mismatched-200` real recall and insertions are first-class
  rows when that comparison is requested.
- No row is dropped because its direction is inconvenient. A missing CI renders
  `n/a` and feeds `INCONCLUSIVE`.

## 3. Term-level appendix

Recovered / lost / inserted counts for the appendix arm, split by origin:

| Origin | Meaning |
|---|---|
| real | Glossary terms the reference actually spoke. |
| fictional | Plausible but non-existent terms used as a control. |
| oov | In-domain terms outside the supplied list. |

Insertions are reported outside the recall denominator. The table never
replaces the per-arm totals in section 2; it explains them.

## 4. Verdict

Exactly one of three tokens, in bold, followed by the reason and the rule:

- **PASS** - real-recall CI lower bound is at or above the pre-registered
  recall margin AND the insertions-per-utterance CI upper bound is at or below
  the insertion cap.
- **FAIL** - the recall lower bound breached the margin or the insertion upper
  bound breached the cap.
- **INCONCLUSIVE** - fewer than two paired calls, a missing bound, or a CI too
  wide to decide. A wide or missing CI is never PASS, and the pre-registered
  planned n is never treated as evidence. One call is always INCONCLUSIVE.

The verdict is a non-inferiority decision rule, not a significance test. No
significance test, test statistic, or multiplicity-adjusted significance claim
appears anywhere in the report; the decision rests only on the two CI bounds
above.

## 5. Descriptive lift (secondary)

A single table with Metric, Estimate and 95% CI, plus a plain reading:

- CI excludes zero: "descriptive only, not a causal claim".
- CI includes zero: "no lift is claimed".

Lift never upgrades the section 4 verdict and never appears as a headline
result. The primary question is harm, not gain.

## 6. Claims register

Three subsections, always present, empty if nothing qualifies:

- **Verified** - reproduced from the scored artifacts and the stamped
  provenance. Only these may be stated as fact.
- **Inferred** - supported but not yet reproduced; labelled as to-validate.
- **Unverified** - hypotheses, vendor claims and design targets; never
  presented as measured results.

Every entry carries the claim `text` and its `basis` (the artifact, table row or
document that supports it). A claim without a basis does not enter the register.

## 7. Synthetic-audio and circularity disclosure

Two required subsections:

- **Synthetic audio** - when TTS audio is used, state that it is internal
  harness validation only, not evidence about real customer calls, and never a
  real-world result.
- **Circularity** - keyterms are selected from the baseline pass-1 transcript
  and call metadata, never from the reference script; the baseline arm is also
  the selector input, so any lift is descriptive rather than independent.

The disclosure is not optional boilerplate: a report that uses synthetic audio
or a baseline-derived selection without it is not reportable.

## Report-writing rules

1. Every number comes from a scored artifact; no number is transcribed by hand.
2. Percentages carry their numerator and denominator, including decoder ignore
   and insertions per utterance.
3. Interval bounds are signed to three decimals and always labelled 95% CI.
4. Verdict language is copied from the rule; do not soften FAIL or sharpen
   INCONCLUSIVE.
5. No significance test belongs in the report. The pre-registered CI rule is
   the only decision mechanism.
6. Synthetic and circularity disclosures travel with the report to every reader,
   including a static page or a slide.

## Appendix A - Filled sample

Illustrative sample only. The values below are synthetic and are not a measured
result for any customer, call or model.

```markdown
# Keyterm Health Report - c00

**Internal harness validation - not for external distribution.**

## 1. Provenance

| Field | Value |
|---|---|
| Model | prisma-v3.0 |
| Canon version | 3.1.0 |
| Context hash | a1b2c3d4e5f6a7b8c9d0 |
| Seed | 0 |
| Audio hash | sha256:0011223344556677 |
| Audio chain | 16k -> 8k -> G.711 -> 8k |
| Date | 2026-11-09 |

## 2. Results per arm

| Arm | Real recall | Fictional recall | OOV recall | Insertions / utterance | WER | Decoder ignore |
|---|---|---|---|---|---|---|
| baseline | 28/40 (70.0%) | 2/4 (50.0%) | 0/2 (0.0%) | 0/40 = 0.00 | 8.0% | 4/40 (10.0%) |
| selected-200 | 36/40 (90.0%) | 3/4 (75.0%) | 1/2 (50.0%) | 8/40 = 0.20 | 7.0% | 2/40 (5.0%) |

Decoder ignore is reported as numerator/denominator: spoken context terms still missed / spoken context terms.

### Paired deltas (95% CI)

| Comparison | Metric | Delta | 95% CI | Calls |
|---|---|---|---|---|
| selected-200 vs baseline | real_recall | +0.200 | [+0.200, +0.200] | 4 |
| selected-200 vs baseline | insertions_per_utterance | +0.200 | [+0.200, +0.200] | 4 |

## 3. Term-level appendix

Arm: selected-200

| Origin | Recovered | Lost | Inserted |
|---|---|---|---|
| real | 2 | 1 | 1 |
| fictional | 1 | 1 | 0 |
| oov | 0 | 1 | 0 |

## 4. Verdict

**PASS**

Real-term recall stayed non-inferior (CI lower bound >= -0.05) and the insertion CI upper bound stayed within the +0.50 cap.

Rule: real-recall CI lower bound >= -0.05 and insertions-per-utterance CI upper bound <= +0.50.
A wide or missing CI yields INCONCLUSIVE, never PASS.

## 5. Descriptive lift (secondary)

| Metric | Estimate | 95% CI | Reading |
|---|---|---|---|
| real_recall | +0.200 | [+0.200, +0.200] | CI excludes zero; descriptive only, not a causal claim. |

## 6. Claims register

### Verified

- Selected-200 recovered 36 of 40 real-term opportunities on this fixture (basis: scored transcript, CANON_VERSION 3.1.0, context hash a1b2c3d4e5f6a7b8c9d0).
- Insertions stayed at 0.20 per utterance, inside the +0.50 cap (basis: paired deltas table, section 2).

### Inferred

- The same list is expected to hold on a second speaker cohort (basis: design section 4; to validate).

### Unverified

- A fixed list chosen by hand beats a per-call selection in production (basis: customer hypothesis; no measurement).

## 7. Synthetic-audio and circularity disclosure

### Synthetic audio

Synthetic (TTS) audio, when used, is internal harness validation only. It is not evidence about real customer calls and must not be presented as a real-world result.

### Circularity

Keyterms are selected from the baseline pass-1 transcript and call metadata, never from the reference script, so the selected arm is not scored on terms it was handed. The baseline arm is also the selector input, so any lift is descriptive rather than independent.
```
