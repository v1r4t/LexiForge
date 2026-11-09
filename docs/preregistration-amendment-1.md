# LexiForge — Pre-registration Amendment 1

**Parent document:** [`docs/preregistration.md`](preregistration.md) (2026-10-29).
**Date:** 2026-11-09. **Status:** recorded and signed **before any pass-2 data
exists**. At signing the workspace contains no `runs/`, `audio/`, `refs/`, or
`transcripts/` output, and no measured result has been inspected.

**Effect.** This amendment is **additive**. It adds no confirmatory claim, does
not change the closed family `{H1, H2}` or its directions, does not change the
frozen metric definitions in §3 of the parent document, and does not alter the
analysis-freedom freeze in §7. It binds how already-frozen items are labelled and
reported, and records which supporting analyses are exploratory. Where this
document and the parent disagree on wording, the parent's frozen definitions
govern; this document supplies the interpretation recorded before data.

---

## 1. Confirmatory family is unchanged

The confirmatory family remains exactly **{H1, H2}**, with the pre-stated
directions from parent §1:

- **H1:** `mismatched-200 < baseline` on real-term recall.
- **H2:** `mismatched-200 > baseline` on glossary-term insertions per utterance.

Holm remains stepwise at alpha 0.05 over exactly two tests: the smallest p is
tested at **0.025**, the second at **0.05**. Nothing added by this amendment
enters that family, receives a confirmatory p-value, or may be substituted for
H1 or H2. The claim ladder in parent §8 is unchanged.

## 2. `oracle-200` is a positive control, outside the family

`oracle-200` is the **positive control**, not a confirmatory endpoint and not a
product-lift claim. It is constructed as the spoken terms for a call first, then
seeded non-true padding to an exact budget of 200; the construction is
deterministic and byte-stable across processes.

- **Contrast:** `oracle-200 − mismatched-200` on real-term recall, paired by
  call. The expectation is a large benefit; a small or zero benefit means the
  pipeline is broken.
- **Reporting:** point estimate and 95% CI **only**. The control receives **no
  p-value**, is **excluded from Holm**, and cannot be reported as evidence that
  relevance helps in deployment.
- **Failure rule:** if the control fails, H1 and H2 are uninterpretable; the
  study is reported as failed under parent §8(1), with no confirmatory p-values.
- **Binding implementation:** the pre-registered analysis reports the control
  under a distinct `positive_control` result carrying a CI and no p-value, while
  `holm` is computed over exactly the two confirmatory tests.

`selected-200` remains the intervention and `oracle-200` must not be presented
as the selected arm. Any descriptive lift from selection is reported separately
and remains descriptive under parent §9.

## 3. `static-head-200` is secondary

The fixed top-frequency list is frozen under the label **`static-head-200`**.
The optional `static-200` arm named in `docs/keyterm-health-poc.md` §2/§4 is the
same arm and must be reported under the frozen `static-head-200` label.

- **Role:** practice/stale-list check, exploratory list item 1 of parent §4.
  It is **secondary**, not confirmatory.
- **Construction:** exactly 200 terms from the fixed core-200 set, identical for
  every call, hypothesis, and call type. It is never padded or resized.
- **Reporting:** paired with `baseline` using simultaneous intervals and **no
  p-value**. It cannot support, rescue, or replace H1/H2.
- **Interpretation:** a stale list is not a mismatched list. A `static-head-200`
  result does not establish the H1/H2 mechanism and is never described as harm
  from an irrelevant list.

## 4. Sample size: n=20 target, n=4 descriptive fallback

**Target.** The confirmatory target is **20 calls** (c00–c19) × 5 utterances =
100 files, 20 call clusters, and approximately 90 real-term occurrences. The
target and the ~20 percentage-point minimum detectable effect for H1 remain as
stated in parent §5. The script set is defined by deterministic regeneration from
the seeded assignment, so that every script id resolves and no call silently
loses an arm; c00–c03 remain byte-fixed, and any byte diff there is a
stop-and-review event, not a licence to re-steer scripts.

**Fallback.** If only **4 calls** are available (the pilot calls c01–c04, 20
utterances), the study may be reported **descriptively only**. The fallback is
not a confirmatory study and must be labelled `INCONCLUSIVE`; its results may
support the mechanism/harness step of the claim ladder but not H1 or H2.

**Why n=4 cannot support the recall margin.** This is fixed now, before data,
so a later four-call result cannot be promoted after inspection:

1. **No attainable rejection.** A paired sign-flip permutation over 4 clusters
   has 2^4 = 16 equiprobable sign assignments. In the best case, with all four
   deltas in the pre-stated direction, the smallest attainable one-sided p is
   **1/16 = 0.0625** (two-sided 0.125). That exceeds 0.05 and is far above
   Holm's smallest threshold of 0.025. No possible four-call outcome can reject
   H1 or H2 at the pre-registered alpha.
2. **No usable variance or MDE.** Four clusters give roughly 2.5 degrees of
   freedom (design §7). The interval is too wide to locate the
   ~20 pp target effect, let alone the −5 pp non-inferiority margin used by the
   POC verdict. A four-call MDE must not be reported as if it were the study's
   MDE.
3. **Too few events.** Four calls contribute about 18 real-term occurrences and
   at plausible H2 rates only ~1–6 insertion events, against the ~90 occurrences
   and 5–30 events the target was sized for. H2 also falls under the parent §6
   floor rule in most four-call outcomes: **untested at this sensitivity**, not
   null.
4. **Corpus failure still applies.** Parent §8(4) declares the confirmatory
   study failed below 18 calls. The n=4 fallback does not override that rule; it
   is an explicitly descriptive pilot that is excluded from the confirmatory
   report and from any claim of safety or harm.

No four-call p-value, confidence-based rejection, or "near-significant" reading
may be reported. A reproducible four-call null remains inconclusive, not
evidence of safety.

## 5. Term-present-anywhere is a sensitivity metric only

A **term-present-anywhere** score is added as a **sensitivity metric**. It asks
whether the H1/H2 conclusions depend on strict span/position alignment; it does
**not** replace the frozen matcher and is **not** a confirmatory endpoint.

- **Definition:** token-boundary matching of any accepted alias surface for a
  term **anywhere** in the hypothesis, counted once per reference occurrence
  (repeats count per occurrence). It relaxes ordering and position only; it does
  not relax term identity, token boundaries, or canonicalisation. A string such
  as `NEFTAA` does not match `NEFT`, and Latin and Devanagari surfaces remain
  distinct under the frozen canonicaliser.
- **Relationship to H1:** `strict` is the parent §3 H1 definition. `anywhere`
  can only be equal to or larger than `strict`; the gap is the reported
  sensitivity, not a second recall estimate to choose between.
- **Reporting:** appendix/sensitivity table with simultaneous intervals and **no
  p-value**. It is never passed to `verdict()`, never used to gate the study, and
  never substituted for H1 or H2. If `strict` and `anywhere` disagree in
  direction, the **strict frozen metric governs** and the disagreement is
  disclosed; the more favourable metric is not selected.
- **No metric rewrite:** parent §3 remains binding. This addition is listed as
  exploratory/sensitivity, consistent with parent §4.

## 6. Alias audit is proposal-only; the alias table stays frozen

An alias/transliteration audit may report collisions, missing spoken forms,
cross-script duplicates, and **proposed** aliases, tagged only with an allowed
source: authoring variant, rule-generated transliteration, or a pre-freeze
attested list. ASR-derived proposals are inadmissible and must be rejected
loudly. A collision exits non-zero and is escalated, never silently repaired.

- **Proposal-only:** the audit writes a report under `runs/` and **never edits**
  `data/glossary.json`, `data/lexicon.json`, or any alias table. It has no
  automatic apply path. Its output is a worklist, not evidence, and not a metric.
- **Table frozen:** the alias table remains frozen under parent §7(3). The audit
  cannot unfreeze it, and no proposal becomes active merely because the audit
  reports it.
- **Adoption rule:** a proposal may be adopted only through a separate dated
  amendment signed **before** pass-2 data, and only from an allowed source. Any
  post-data edit to the alias table, or any alias derived from ASR output, voids
  confirmatory status for the affected metrics. Because the matcher and
  canonicaliser are frozen (`canon.py`, `score/match.py`), a collision is a
  blocker to review, not a code change.

## 7. What this amendment does not do

1. It adds **no** confirmatory claim, endpoint, stratum, or subgroup.
2. It does not change H1/H2 definitions, directions, unit, clustering, or the
   Holm procedure.
3. It does not change parent §7's freeze list or permit post-data choices.
4. It does not rewrite `docs/design.md`; the design remains the approved source
   for the experiment.
5. It claims **no measured result**. Any run remains labelled internal harness
   validation until the pre-registered gates and provenance requirements pass.

## 8. Signature

Recorded **2026-11-09**, before any pass-2 data exists. Confirmatory family
`{H1, H2}` remains closed; `oracle-200` remains outside it; `static-head-200`
remains secondary; n=20 is the target and n=4 is descriptive only;
term-present-anywhere is sensitivity only; alias proposals do not alter the
frozen table.

Signed: ______________________  Date: 2026-11-09

Study owner: ______________________  Date: 2026-11-09
