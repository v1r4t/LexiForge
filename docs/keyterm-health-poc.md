# Keyterm Health POC

**Status:** design phase — no measured results. Internal harness validation only.  
**Date:** 2026-11-07  
**Scope:** Measurement-led POC to test whether 200 keyterm slots help or hurt on customer audio/glossary with Gnani Prisma v3.0.

## 1. Measurement-led POC (not a claim of lift)

This is a **measurement-led** POC, not a marketing claim. We measure the effect of keyterm context under controlled conditions:
- Same audio, same model, same format. Only the keyterm list changes.
- Selection input is the **baseline pass-1 transcript + call metadata, never the reference script** (prevents circularity).
- All results are reported with uncertainty; **no measured results are claimed in this document**.
- TTS-generated audio (Phases 1–2) is **internal harness validation only** and must never be presented as real customer evidence.

## 2. Pre-registration (frozen)

Pre-registered before any pass-2 data exists (see also [`docs/preregistration.md`](preregistration.md)):

- **Arms** (exactly 5, budget 200 where specified): `baseline` (none), `selected-200` (compiled from glossary + pass-1 + metadata), `mismatched-200` (200 off-domain, zero overlap), `hard-negative-200` (200 phonetically/orthographically close), `static-200` (optional fixed list).
- **Pinned config**: `format=transcribe` and `language_code=hi-IN,en-IN` across all arms. Record `detected_language_code` per job/segment.
- **Metrics**: real-term recall (H1 stratum), fictional/OOV recall, insertions per utterance (H2), WER (guardrail), decoder-ignore rate (with numerator/denominator). 
- **Unit of analysis**: (utterance, term) pairs clustered by call; replicates collapsed at item level first.
- **Primary verdict**: non-inferiority on harm, not lift.
  - Recall non-inferiority: 95% CI lower bound of (selected − baseline) real-term recall ≥ **−5pp**.
  - Insertion cap: 95% CI upper bound of (selected − baseline) insertions per utterance ≤ **+0.5** (calibrate after Phase 2).
  - If CI too wide to decide either → **INCONCLUSIVE**.
- **Secondary**: lift is descriptive only (report point estimate + 95% CI; do not claim lift if CI includes 0).
- **Inference**: paired sign-flip permutation across calls (design-based); wild cluster bootstrap-t as cross-check only; Holm correction over confirmatory family as specified.
- **Power**: recompute MDE from observed cluster variance after Phase 2; do not rely on fixed-n power claims from synthetic design alone.

## 3. Internal-only Phases 1–2 (synthetic)

- **Phase 0 – Setup/validity (0 credits):** Gnani Timbre TTS client (fallback `edge-tts` if scope missing), scope check, **matcher gold set** (30 hand-labelled cases) targeting ≥0.98 span precision/recall before trusting scores, **glossary coverage check** (fraction of glossary appearing in scripts). Selector must choose from full glossary, not echo scripts.
- **Phase 1 – One-call internal validation:** TTS `data/scripts/c00.json` (5 turns), concatenate, make telephony-like (8 kHz, G.711 μ-law, light noise), record processing chain. Run 4 Batch jobs (baseline, selected-200, mismatched-200, hard-negative-200), pin format/language, score with frozen matcher. Report labelled **internal harness validation – not for external distribution**. Log credits.
- **Phase 2 – Four-call pilot (only if Phase 1 cheap):** `c00–c03`, 4 arms = 16 requests. Descriptive paired deltas only (no p-values). Recompute MDE from observed variance. Report labelled **internal only**.
- **Synthetic disclosure:** When TTS is used, reports must include synthetic-audio and circularity disclosure (§6). Never publish Phase 1–2 as real-world results.

## 4. Arms, metrics, non-inferiority verdict

### Arms
| Arm | Keyterms | Purpose |
|---|---|---|
| baseline | none | Unaided model; produces pass-1 transcript for selector |
| selected-200 | compiled from glossary + pass-1 transcript + metadata | Intervention being tested |
| mismatched-200 | 200 off-domain terms (zero overlap asserted) | Negative control |
| hard-negative-200 | 200 phonetically/orthographically close to expected terms | Insertion/loss test (more sensitive than mismatched) |
| static-200 | fixed list (optional) | What many customers do today |

### Metrics
- **Real-term recall** (H1): numerator = occurrences matched by frozen matcher (longest-span exact alias match after 8 frozen canonicalisation steps); denominator = real-term occurrences in reconciled reference (audio wins). Clustered by call.
- **Glossary-term insertions per utterance** (H2): numerator = inserted glossary-term spans (token-aligned; insertion if aligns to different ref term or nothing; same-term alignment is a hit). Denominator = utterances.
- **Fictional/OOV recall**: benefit/guardrail strata.
- **WER**: guardrail (raw); folded WER demoted to appendix if used.
- **Decoder-ignore rate**: fraction of context terms the reference says were spoken that the hypothesis still missed — reported with **numerator/denominator**, not bare percentage.

### Non-inferiority verdict
- **Recall non-inferiority:** 95% CI lower bound of (selected − baseline) real-term recall ≥ −5pp.
- **Insertion cap:** 95% CI upper bound of (selected − baseline) insertions per utterance ≤ +0.5.
- **Verdict**: `PASS` if both hold; `FAIL` if either violated in harmful direction; `INCONCLUSIVE` if CIs too wide to decide.  
  Lift is **descriptive only** — never claimed as primary; do not claim lift if CI includes 0.

## 5. Claims register

### Verified
- Gnani Prisma v3.0 keyterm limits/fields/batch combinations/format options (from docs).
- Gnani's published context warning and 60-public-clip test claim.
- Local harness state: **466 tests pass** (current repo state). Tests prove execution, not matcher correctness — hence matcher gold set requirement.

### Inferred / to validate
- Customer glossary is 2000+ terms (synthetic design uses 2000; not an industry fact).
- Customers pick 200 by hand and reuse one list.
- Selected-200 beats baseline on real calls (unverified; must be measured).
- Competitor differentiation vs Sarvam/Deepgram/ElevenLabs — unverified, not usable yet.

### What this POC does NOT claim
- No measured results are claimed here. Phase 1–2 are internal harness validation only.
- No causal claim about fixed lists in production deployment from synthetic audio alone.
- No claim beyond tested conditions (clean/read speech, synthetic glossary, limited speakers as per design).
- No guarantee of lift; primary question is harm/non-inferiority under pre-registered rules.

## 6. Report structure (Keyterm Health Report)

Every report must include:
1. **Provenance**: model, `CANON_VERSION`, context hash, seed, audio hash, audio-processing chain, date.
2. **Results per arm** + paired deltas + 95% CI.
3. **Term-level appendix**: recovered/lost/inserted by real/fictional/OOV.
4. **Verdict**: `PASS`/`FAIL`/`INCONCLUSIVE` under pre-registered non-inferiority rule.
5. **Descriptive lift with CI** (secondary).
6. **Claims register**: verified/inferred/unverified.
7. **Synthetic-audio and circularity disclosure** (when TTS/internal harness validation used).

## 7. Integration notes (Gnani)
- Prisma v3.0 Batch: `config.keyterms` max 200; `config.topic` 30–1600; `config.speaker_names` 1–4. Allowed combinations: keyterms | topic | topic+keyterms | speaker_names alone.
- `config.format`: `verbatim` | `transcribe` | `codemix` — **pin `transcribe` across all arms**.
- Language: `language_code` `hi-IN,en-IN` pinned; record `detected_language_code` per job/segment (v3.0 identifies language per segment on Batch).
- One job per call (or per pack) to control keyterms cleanly. Batch preferred over REST for longer audio.
- Score **raw transcripts only** (substitution can hide recognition errors). Decorations like substitution are not relied on for measurement.
- `max_rps=1` in production; log credits after every gate.

## 8. References
- [`docs/design.md`](design.md) — full experimental design
- [`docs/preregistration.md`](preregistration.md) — frozen confirmatory claims/metrics/analysis
- [`docs/runbook.md`](runbook.md) — operational procedures
- [`README.md`](../README.md) — project overview and current status
