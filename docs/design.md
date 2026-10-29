# LexiForge — Design

**Status:** approved 2026-10-29. **Deadline:** 2026-11-10.

## 1. The claim

A bank's voice agent gets **200 keyterm slots per call** and holds a **2,000-term** product glossary. A fixed list is stale for most calls. The vendor documents that context can make a model *less* accurate, then publishes no measurement of that cost.

This project measures it.

**H1 — an irrelevant list costs recognized words.** `mismatched-200 < baseline` on **real** terms — NEFT, UPI, KYC, IFSC — which baseline already recognizes. These are the only terms with room to fall.

**H2 — an irrelevant list invents words.** `mismatched-200 > baseline` in glossary-term insertions per utterance. Baseline carries no list, so its rate is near zero and any insertion is unambiguous harm.

The benefit of a *relevant* list — `oracle-200 − mismatched-200` — is a **positive control**, not a confirmatory claim. It should be large. If it is not, the pipeline is broken and both nulls are uninterpretable.

Everything is measured on **clean, read speech with a synthetic glossary, four speakers from one accent region**. That sentence belongs in the abstract, not buried.

Neither hypothesis says a fixed list causes harm. `static-200` vs `baseline` is reported secondary, and shows how much of this harm appears with a merely stale list.

## 2. Conditions

| Condition | Context | Role |
|---|---|---|
| baseline | none | harm reference |
| mismatched-200 | 200 off-domain terms, zero overlap asserted | **H1, H2 arm** |
| static-head-200 | fixed top-frequency 200 | practice check (secondary) |
| oracle-minimal | spoken terms only | control, floor |
| oracle-200 | spoken terms + seeded non-true padding | control, ceiling |
| random-200 | seeded random 200 | C2 comparator |
| adaptive-200 | selected + seeded non-true padding to 200 | C2, truncation policy |
| dilution | oracle-minimal + off-domain filler to 200 | displacement (exploratory) |
| near-miss | mismatched truncated to pass-1 phonetic neighbours | pollution (exploratory) |
| sweep 5 / 50 | adaptive at smaller budgets | dose-response (exploratory) |

`topic` is held constant per call across every condition, derived from call metadata only. `topic`-only and `speaker_names`-only arms are cut — no power, no budget.

**Confirmatory family: {H1, H2}.** Positive control sits outside it. Everything else is exploratory, reported with simultaneous intervals and no p-values.

**Adaptive-200 is padded to exactly 200** with seeded non-true terms, matching oracle-200's construction, so C2 compares selection *quality* at equal budget rather than a short list against a long one. The natural selected-set size is reported separately per call, because underfill is the selector's actual policy.

## 3. Corpus

- 20 synthetic calls × 5 utterances = 100 files, each ≤30 s. Strict AGT/CUS/AGT/CUS/AGT.
- **4–5 real terms and 3–4 fictional terms per call**, ~1.6 occurrences per utterance overall. This is denser than real call speech — deliberately, because H1 needs ~90 real-term occurrences to have any chance of resolving a 10-point drop. The inflation is disclosed in §9, not hidden.
- 12 banking categories; mechanical real/fictional split — fictional terms carry a nonce root and are Levenshtein ≥3 from every real entry, and ≥3 from one another.
- Three mismatched-domain packs: insurance→UPI, forex/branch→collections, mandate→card-fraud. Zero overlap asserted against expected **real and fictional** terms.
- 10/20 calls carry a role-confusable hard-negative pair; 6/20 carry one spoken term absent from the glossary.
- Reference format `codemix`: Latin product names and acronyms, Devanagari Hindi, digits.
- Recording: one session per call, one device, guide for consistency but **no rehearsal drill**, first take by default, retake only if a target term is unintelligible, consent, 6-item QC.
- References: two-pass — blind transcription first, then reconcile against the script with **audio winning**. Verifier blind to condition and to the glossary. ~3.5 min/file.

## 4. Pipeline

1. **Glossary** → `data/glossary.json`. Aliases only from authoring variants, rule-generated transliterations, or pre-freeze attested lists. Never from ASR output. Bulk entries generated from nonce roots and validated; human effort on the ~250–300 entries that get spoken, the confusable pairs, and `core-200`.
2. **Term assignment** → `data/assignment.json`. Which terms appear in which call is drawn by seed *before* the author sees `core-200`, so scripts cannot be steered to make static-200 look bad.
3. **Scripts** → `data/scripts/`. Ten mechanical checks, including real-term density and mismatched zero-overlap.
4. **Audio** → `audio/`, naming `c##_t##_s##_k##`. Rejected takes quarantined.
5. **References** → `refs/`, arbitration log, deviation flag per file.
6. **Contexts** → `contexts/<condition>/c##.json`. JSON array, NFC, one fixed sort key, deduped before the 200-cap, mismatched asserts zero overlap against the pinned expected-term list.
7. **Pass 1** → one no-context job over all 100 files.
8. **Selection** → client-side, per call, from pass-1 hypotheses + glossary + metadata only.
9. **Pass 2** → one job per call per condition.
10. **Score** → frozen matcher, stratified metrics.
11. **Inference** → pre-registered contrasts only.

**Harness:** 8-state local machine; SQLite ledger keyed uniquely on `(condition, conversation, replicate)` so a restart cannot double-submit; write-ahead `client_job_id` persisted *before* the POST, since a crash between POST and ledger write is the one window that bills twice; context hash per job; 504 → retry once; 429 → jittered backoff; empty transcript is not a failure; per-call coverage gate rather than a global one.

## 5. Selection and scoring

**Selector:** `S = 0.55·Lex + 0.25·Phon + 0.20·Prior`, MMR redundancy penalty, threshold. Phonetic component is a Hinglish consonant skeleton (aspiration collapse, retroflex merge, schwa deletion, acronym letter-joining) with veto rules that stop it merging hard-negative pairs. Leakage test runs with `refs/` unreadable and asserts output is unchanged.

**Matcher:** eight frozen steps — NFC, nukta kept, chandrabindu→anusvara, no transliteration, Latin casefold, hyphen→space, acronym spacing collapsed, no word/digit folding. Longest-span exact alias match only. Collision test proves no hard-negative pair canonicalises to the same key.

**Insertion, defined before the pilot:** token-align reference to hypothesis; a hypothesis span mapping to a glossary term counts as an insertion if it aligns to a *different* reference term, or to nothing. Same-term alignment is a hit. This prevents a correct transcription of an ordinary word being scored as an insertion because it sounds like a glossary term.

**Metrics:** real-term recall (H1, primary stratum), insertions per utterance (H2), fictional-term recall (benefit stratum, control side), false insertions per 100 unspoken in-list exposures (guardrail), raw WER (guardrail; folded WER demoted to appendix), selector coverage and retrieval-at-200 (mechanism), decoder-ignore rate — terms selected into context yet still missed.

## 6. Analysis

Unit is the (utterance, term) pair, clustered by call. Replicates collapse by arithmetic mean **at item level first**, then the call-clustered statistic is computed — never collapse across calls.

**Primary inference is a sign-flip permutation across 20 conversations**, paired, which is design-based: it is valid because mismatched-domain assignment was seeded per call. Wild cluster bootstrap-t is reported as a cross-check; if they disagree, the permutation governs.

Holm over two tests: smallest p at 0.025, second at 0.05. The positive control is not in the family.

**Adjudication is a calibration audit, not a test.** Discordant items first (~150 cap), plus a concordant 75+75 sample stratified ≥35 per arm for baseline and adaptive. Blind to condition and to the matcher's verdict. The output is a bound on the between-arm false-credit difference with a pre-stated invalidation rule: if differential bias could plausibly account for the observed H1/H2 effect, the affected claim is withdrawn. No p-value, no IPW — the sample cannot support a formal estimate.

## 7. Decision rules

**Pilot = calls c01–c04 of the final corpus**, scripts frozen first. A four-cluster variance estimate has ~2.5 degrees of freedom and cannot support a power gate.

**G1 (Nov 2) gates only what four calls settle:**

1. Plumbing works end to end.
2. Baseline real-term recall between 0.85 and 0.99; fictional recall between 0.30 and 0.70. If real-term misses cluster on letter-spelled acronyms, that is a canonicalisation defect — fix before freeze, using **pass-1 output only**, which is context-free and legitimate calibration.
3. Canonicalisation: ≥90% of true spans match.

Two tripwires, reported not gated: per-file flip rate across three baseline runs (expand to five if ≥10%), and pilot directional deltas (abort if either is inverted).

**H2 floor rule, written now:** if c01–c04 show zero mismatched-arm insertions, H2 is reported as **untested at this sensitivity**, and the false-insertion claim is carried descriptively by the graded close-pair set.

**Expected H2 events:** 5–30 across the corpus at plausible rates of 0.05–0.30 per utterance. Statistic is exact sign-flip permutation on per-conversation counts.

**Claim ladder:** H1+H2 → H2 alone with H1 inconclusive → mechanism only → harness only. A reproducible null is a legitimate submission.

**First to drop if Nov 2 slips:** the near-miss arm, then dilution.

## 8. Calendar

| Date | Work | Gate |
|---|---|---|
| Oct 29 | key check, concurrency probe, glossary generator | — |
| Oct 30 | glossary curated, `core-200` frozen, term assignment seeded | — |
| Oct 31 | scripts written, validated, frozen | — |
| Nov 1 | record c01–c04 | — |
| Nov 2 | pilot end to end; **fallback demo clip cut from pilot data** | **G1** |
| Nov 3–4 | record c05–c20; reference verification overlaps from Nov 1 | — |
| Nov 5 | references complete; matcher frozen | **G2** |
| Nov 6–7 | pass 1 → selection → pass 2 (~287 jobs) | — |
| Nov 8 | score, adjudicate, analyse | **G3** |
| Nov 9 | app, demo, 16:00 freeze; morning is the only buffer | — |
| Nov 10 | submit | — |

**Recording order is prefix-balanced:** the six speaker pairs rotate, so any prefix ≤6 covers every pair once. A dropout leaves a balanced design rather than a collapsed pair. Substitution rule: a replacement passing the guide that day, or drop to three speakers and 18 calls, documented.

The demo clip is cut on **Nov 2 from pilot data**, so the P0 deliverable exists before the analysis that might invalidate it.

## 9. Limitations, stated up front

Four speakers, one accent region, clean audio, fictional brands, scripted then read aloud. **Density is ~1.6 terms per utterance, above real call speech**, because H1 requires it; context effects are therefore inflated relative to organic conversation. Scripts were written by someone who knows the glossary — the one threat the design cannot eliminate, so effect sizes read as upper bounds under best-case form predictability. Mismatched-200 is a worst case, not a typical deployment. Term recall is necessary but not sufficient for deployment value. At ~90 real-term occurrences, H1 resolves only large drops; a null is inconclusive, not evidence of safety.

## 10. Cost, rate limit, and wall clock

₹27.00 per audio hour for STT, REST and Batch alike; 1 credit = ₹1; 60 requests/minute for Batch. Balance 5,000 credits ≈ 11,100 minutes.

The matrix is ~420 billed minutes — seven audio hours — at **~₹190**, under 4% of the balance. Cost is not a constraint; human hours are. 287 jobs fit inside five minutes of the submission allowance; polling at 15-second intervals is ~18 requests/minute. Server-side job parallelism is unstated and is measured by the Oct 29 probe.

## 11. What is being built

`lexiforge/` — harness, selectors, matcher, scoring, analysis. `data/` — glossary, core-200, assignment, scripts (committed). `audio/`, `refs/`, `transcripts/` — gitignored. `web/` — static three-screen gallery. `docs/` — this document, pre-registration, notes.

Stack: Python 3.11 with `httpx`, `pydantic`, `typer`, `rapidfuzz`, `numpy`/`scipy`; SQLite + JSONL; FastAPI; React + Vite + Tailwind; ffmpeg. No model training, no fine-tuning, no streaming.
