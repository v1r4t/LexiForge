# LexiForge — Pre-registration

**Date:** 2026-10-29. **Status:** committed before any pass-2 data exists. This document freezes the confirmatory claims, metrics, family, power, and analysis freedoms. Design reference: `docs/design.md` (approved 2026-10-29).

## 1. Scope and exact claim

Measurement only, on clean read speech with a synthetic glossary, four speakers from one accent region. No causal claim about fixed lists in deployment; no claim beyond the tested conditions.

Quoted from design §1:

- **H1 — an irrelevant list costs recognized words.** `mismatched-200 < baseline` on **real** terms — NEFT, UPI, KYC, IFSC — which baseline already recognizes. These are the only terms with room to fall.
- **H2 — an irrelevant list invents words.** `mismatched-200 > baseline` in glossary-term insertions per utterance. Baseline carries no list, so its rate is near zero and any insertion is unambiguous harm.

Conditions: `baseline` (no context, harm reference) vs `mismatched-200` (200 off-domain terms, zero overlap asserted against expected real and fictional terms). `topic` held constant per call across conditions.

## 2. Positive control

`oracle-200 − mismatched-200` is a **positive control**, not a confirmatory claim. It should be large. A failed control (small or zero benefit of a relevant list) means the pipeline is broken and **both H1 and H2 are uninterpretable**. In that case no confirmatory inference is drawn; the study is reported as failed per §8.

## 3. Frozen metric definitions

- **H1 metric: real-term recall (primary stratum).** Denominator: real-term occurrences in the reconciled reference (audio wins). Numerator: occurrences matched by the frozen matcher (longest-span exact alias match after the eight frozen canonicalisation steps). Unit is the (utterance, term) pair, clustered by call. Contrast: `mismatched-200 − baseline`, paired by call. Directional: H1 is `mismatched-200 < baseline`.
- **H2 metric: glossary-term insertions per utterance.** Denominator: utterances (100). Numerator: inserted glossary-term spans. Contrast: `mismatched-200 − baseline`, paired by conversation counts. Directional: H2 is `mismatched-200 > baseline`.
- **Operational insertion definition (from design §5), frozen:** token-align reference to hypothesis; a hypothesis span mapping to a glossary term counts as an insertion if it aligns to a *different* reference term, or to nothing. Same-term alignment is a hit. A correct transcription of an ordinary word is therefore never scored as an insertion because it sounds like a glossary term.

No other metric definition may be substituted for H1 or H2 after this date.

## 4. Confirmatory family and exploratory list

**Closed confirmatory family: {H1, H2}.** Stepwise Holm at alpha 0.05: smallest p tested at 0.025, second at 0.05. The positive control is outside the family. Rejection requires the pre-stated direction.

**Exploratory list (closed; reported with simultaneous intervals and no p-values):**

1. `static-head-200` vs `baseline` (stale-list practice check, secondary).
2. Dilution arm (oracle-minimal + off-domain filler to 200; displacement).
3. Near-miss arm (mismatched truncated to pass-1 phonetic neighbours; pollution).
4. Sweep arms (adaptive at budgets 5 / 50; dose-response).
5. Strata and mechanism: fictional-term recall, false insertions per 100 unspoken in-list exposures, selector coverage, retrieval-at-200, decoder-ignore rate.
6. Raw WER guardrail (folded WER in appendix only).
7. Adjudication calibration audit (discordant items plus concordant 75+75 sample; bound on between-arm false-credit difference; no p-value, no IPW).

Nothing outside this list enters the confirmatory report as an inference.

## 5. Sample size and power

20 calls × 5 utterances = 100 files. ~90 real-term occurrences total. 20 clusters (calls). Minimum detectable effect on H1 is ~20 percentage points. **H1 resolves only large drops; a null is inconclusive, not evidence of safety.** Corpus density (~1.6 occurrences per utterance) is deliberately above real call speech to obtain even this power, so effect sizes read as upper bounds.

## 6. H2 floor rule

If calls c01–c04 show zero mismatched-arm insertions, H2 is reported as **untested at this sensitivity**, not as null. The false-insertion claim is then carried descriptively by the graded close-pair set. Expected H2 events under plausible rates (0.05–0.30 per utterance): 5–30 across the corpus.

## 7. Analysis-freedom freeze

The following are frozen on 2026-10-29 and may not change after data are seen:

1. Metric definitions (§3 above).
2. Matcher version (eight frozen canonicalisation steps; longest-span exact alias match only).
3. Alias table (aliases only from authoring variants, rule-generated transliterations, or pre-freeze attested lists; never from ASR output).
4. Stratum boundaries (real vs fictional; mechanical split with nonce root and Levenshtein ≥3).
5. Exclusion rules (retake only if a target term is unintelligible; rejected takes quarantined; deviation flag per file).
6. Replicate counts and collapse rule (replicates collapse by arithmetic mean at item level first, then the call-clustered statistic; never collapse across calls).
7. Permutation specification (paired sign-flip permutation across 20 conversations, design-based; wild cluster bootstrap-t as cross-check only; on disagreement the permutation governs).

Calibration from pass-1 (context-free) output before the freeze is legitimate; any use of pass-2 output to alter items 1–7 voids the confirmatory status.

## 8. Stopping rules: declared failed

The study is declared failed and reported as such if any of the following holds:

1. Positive control fails (`oracle-200 − mismatched-200` small or zero): pipeline broken, H1/H2 uninterpretable.
2. G1 calibration fails and is not fixed before freeze: baseline real-term recall outside [0.85, 0.99], fictional recall outside [0.30, 0.70), or canonicalisation below 90% of true spans matched.
3. Pilot tripwire abort: either directional delta inverted on c01–c04 in a way attributable to harness error rather than sampling noise.
4. Corpus or reference failure: dropout below 18 calls, or reference arbitration irreconcilable with audio.

A failed study is reported with the failure reason, the claim ladder step reached (H1+H2 → H2 alone → mechanism only → harness only), and no confirmatory p-values. A reproducible null is not a failure.

## 9. Signature

Pre-registered 2026-10-29, before any pass-2 data exists. Confirmatory family {H1, H2} closed. Holm at 0.05. Freeze list in §7 binding.

Signed: ______________________ Date: 2026-10-29
