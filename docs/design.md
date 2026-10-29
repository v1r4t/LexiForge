# LexiForge — Design

**Status:** draft for approval. **Date:** 2026-10-29. **Deadline:** 2026-11-10.

## 1. The claim

With a 200-term keyterm budget per call, a **mismatched** vocabulary measurably corrupts transcripts compared with a matched one; a cheap per-call selector, built only from a no-context first pass, recovers most of the matched-vocabulary benefit without that corruption.

Two things this is not. It is not "contextual biasing helps" — Gnani publishes that. It is not "our selector beats a static list" — at ~70–75 effective term occurrences the minimum detectable effect is ~20 points, and that comparison is **declared inconclusive in advance**.

The unit of contribution is the **cost of getting the budget wrong**, which the vendor documents as a risk and reports no measurement of.

## 2. Why this shape

| Condition | Context | Exists to |
|---|---|---|
| baseline | none | anchor absolute recall; determinism diagnostic |
| oracle-minimal | spoken terms only | matched ceiling at minimal budget |
| oracle-200 | spoken terms + seeded non-true padding | matched ceiling at full budget (C1 arm) |
| mismatched-200 | 200 out-of-domain terms, zero overlap asserted | corruption arm (C1 arm) |
| random-200 | seeded random 200 | chance-level budget control (C2 arm) |
| static-head-200 | fixed top-frequency 200 | the deployed baseline a team would actually ship |
| adaptive-200 | LexiForge ranker over pass-1 hypotheses | cheap selection (C2 arm) |
| sweep 5/20/50 | adaptive at smaller budgets | dose-response, exploratory |

`topic` is held constant per call across every condition; it is derived from call metadata only, never from the reference. `topic`-only and `speaker_names`-only arms are **cut** — no power, no budget.

**Pre-registered contrasts**, one-sided, superiority margin **+20pp**, Holm over a closed family of two:

- **C1** `oracle-200` vs `mismatched-200`
- **C2** `adaptive-200` vs `random-200`

Everything else — static, oracle-minimal, sweep, strata — is exploratory, reported with simultaneous intervals and no p-values.

## 3. Corpus

- 20 synthetic calls × 5 utterances = 100 files, each ≤30 s. Strict AGT/CUS/AGT/CUS/AGT.
- 12 banking categories; mechanical real/fictional split — fictional terms carry a nonce root and are Levenshtein ≥3 from every real glossary entry.
- Three mismatched-domain packs: insurance→UPI, forex/branch→collections, mandate→card-fraud.
- 4–6 term occurrences per call (~1.0 per utterance). **Density is fixed deliberately**: higher density inflates every context effect. The consequence is a ~20-point MDE, and that is a property of the design, not a defect.
- 4/20 calls carry one out-of-core term (~5–8% of occurrences, 15–20% of distinct types). 6/20 carry one spoken term absent from the glossary. 10/20 carry a role-confusable hard-negative pair.
- Reference format `codemix`: Latin product names and acronyms, Devanagari Hindi, digits.
- **Telephony subset:** 20 files re-encoded to 8 kHz to probe channel sensitivity, reported separately and exploratory. No claim rests on it.
- Recording: one session per call, one device, pronunciation gate before recording, max 3 retakes, consent, 6-item QC.
- References: two-pass — blind transcription first, then reconcile against the script with **audio winning**. Verifier blind to condition and to the glossary. ~3.5 min/file.

## 4. Pipeline

1. **Glossary** → `data/glossary.json`. Aliases only from authoring variants, rule-generated transliterations, or pre-freeze attested lists. **Never from ASR output.** CI asserts the alias file predates the first decode.
2. **Scripts** → `data/scripts/`. Validated against 10 mechanical checks before recording.
3. **Audio** → `audio/`, naming `c##_t##_s##_k##`. Rejected takes quarantined, never deleted silently.
4. **References** → `refs/`, with an arbitration log and a deviation flag per file.
5. **Contexts** → `contexts/<condition>/c##.json`. JSON array, NFC, one fixed sort key across all conditions, deduped before the 200-cap check, mismatched set asserts zero overlap with expected terms.
6. **Pass 1** → one no-context job over all 100 files.
7. **Selection** → client-side, per call, from pass-1 hypotheses + glossary + metadata only.
8. **Pass 2** → one job per call per condition.
9. **Score** → frozen matcher, stratified metrics.
10. **Inference** → pre-registered contrasts only.

**Harness:** 8-state local machine over the remote job lifecycle; SQLite ledger; idempotency key over `(pass, condition, context_hash, sorted file hashes, model, format)`; 504 → retry once; 429 → jittered backoff; an empty transcript is not a failure; per-condition missingness manifest; a condition is invalid only if coverage <80% **and** missingness is non-random.

## 5. Selection and scoring

**Selector:** `S = 0.55·Lex + 0.25·Phon + 0.20·Prior`, with an MMR redundancy penalty and a threshold. It **underfills rather than pads** — padding reintroduces exactly the corruption being measured. The phonetic component is a Hinglish consonant skeleton (aspiration collapse, retroflex merge, schwa deletion, acronym letter-joining) with veto rules that stop it merging hard-negative pairs. A leakage test permutes references and asserts output is unchanged.

**Matcher:** eight frozen canonicalisation steps — NFC, nukta kept, chandrabindu→anusvara, **no transliteration**, Latin casefold, hyphen→space, acronym spacing collapsed, no word/digit folding. Longest-span exact alias match only. A runnable collision test proves no hard-negative pair canonicalises to the same key. ~500-span gold set, specificity ≥0.98 on pairs. Phonetic matching is a **sensitivity analysis only**.

**Metrics:** term recall per reference occurrence (primary; stratified fictional/real, in-core/out-of-core, head/tail). False insertions per 100 unspoken in-list exposures as a guardrail; per 100 tokens as exploratory. WER at two locked levels (raw; fully folded). Selector diagnostics decomposed into coverage, retrieval, ranking. ITT recovery over all pass-1 errors.

## 6. Analysis

Unit is the (utterance, term) pair, clustered by call. Design effect 1.25–2.1 at ICC 0.1–0.4, so naive binomial SEs run 1.1–1.45× too small. Inference is **wild cluster bootstrap-t with Rademacher weights, one per call, at G=20**, with conversation-level randomisation as a cross-check. Replicates collapse by arithmetic mean — never majority vote, never best-of-3.

**Replication:** every arm in a pre-registered contrast gets **three** runs, collapsed by arithmetic mean before pairing. Equal R on both sides is what keeps the paired standard error honest — mean-of-3 against a single run understates it by roughly two-thirds of the run variance. The three baseline runs additionally serve as a determinism diagnostic. At ₹27 per audio hour the extra runs cost ~₹72, so the binding constraint is wall clock, not money.

## 7. Decision rules

**Pilot gate — four calls, before anything scales.** It must return:

1. Baseline term recall between 0.30 and 0.70 — headroom in both directions.
2. Matcher false-credit below 2% on the hard-negative pairs.
3. Paired-delta SD implying an MDE no worse than 25 points.
4. A corruption signal: `oracle-200 − mismatched-200 > 0`.

Plus one check the specialists missed: **canonicalisation against real ASR output**. If more than 10% of true spans fail to match for tokenisation reasons rather than recognition reasons, the metric is miscalibrated and no amount of running fixes it.

**Claim ladder.** If the data will not support the primary claim: directional → mechanism-only → harness-only. Each rung has a pre-stated evidence requirement. A reproducible null is a legitimate submission.

**Backstop.** Demo must be recorded by **Nov 9, 16:00**. Numbers freeze at that point; nothing new runs after it.

## 8. Limitations, stated up front

Four speakers, one accent region, clean audio, fictional brands, scripted and then read aloud. Scripts were written by someone who knows the glossary, which is the one threat the design cannot eliminate — effect sizes should be read as **upper bounds under best-case form predictability**. Term recall is a necessary but not sufficient proxy for deployment value. Only large effects are detectable.

## 9. Cost, rate limit, and wall clock

Pricing, verified on the Gnani API pricing page: **₹27.00 per audio hour** for STT, REST and Batch alike; **1 credit = ₹1**; **60 requests/minute** for Batch. The account holds 5,000 credits — about 11,100 minutes of audio.

The full matrix is ~260 billed minutes, or 4.3 audio hours, so **~₹117** — 2.3% of the balance. With three replicates on the contrast arms it rises to ~₹190, still under 4%. Cost is therefore not a design constraint. Human hours are. Credits buy replication, which is nearly free of labour; they do not buy recording and reference verification, which scale linearly with corpus size. That asymmetry is why the corpus stays at 100 files and the budget goes into replicates.

The 60 requests/minute figure governs **submission**, not processing. The ~270 job creates fit inside five minutes of that allowance, and polling at 15-second intervals is ~18 requests/minute. What the docs do not state is **how many batch jobs run concurrently server-side**; the smoke test submits five jobs at once and records how many reach `IN_PROGRESS` together. That single number sets the Nov 5–6 schedule — with real parallelism the run is under an hour, and if jobs queue it is bounded by per-job processing time.

## 10. What is being built

Repo: `lexiforge/` (harness, selectors, matcher, scoring), `data/` (glossary, core-200, scripts — committed), `audio/` and `refs/` (gitignored if they contain identifiable voices), `web/` (three-screen demo), `docs/` (this document, pre-registration, notes).

Stack: Python 3.11 with `httpx`, `pydantic`, `typer`, `rapidfuzz`, `numpy`/`scipy`; SQLite + JSONL; FastAPI; React + Vite + Tailwind; ffmpeg. No model training, no fine-tuning, no streaming.
