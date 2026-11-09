# POC intake — scope, package, and effort

**Status:** design phase. No measured results are claimed.  
**Date:** 2026-11-09  
**Scope:** how a Keyterm Health POC call set enters the harness, what the customer must supply, what LexiForge supplies, and what one call costs in human effort.

> **Synthetic-audio caveat (read first).** The committed corpus is **synthetic: four speakers, one accent region, scripted then read aloud, ~1.6 glossary terms per utterance** (verified: `docs/design.md` §9, `docs/preregistration.md` §5). Any cost, effort, or timing figure derived from it is an **upper bound / internal harness validation**, not a customer quote and not evidence about real call traffic. Synthetic results must never be presented as real customer evidence.

**Number tags.** `[V]` = verified in this repository (cite given). `[I]` = inferred or assumed for planning; must be re-measured before it is quoted to a customer. A tag applies to the adjacent figure only.

---

## 1. What a POC intake is

A POC intake is one batch of calls scored by the frozen four-arm harness:

| Arm | Keyterms | Role |
|---|---|---|
| `baseline` | none | Harm reference; also produces the pass-1 transcript used for selection |
| `selected-200` | 200 terms from glossary + pass-1 transcript + metadata | Intervention |
| `mismatched-200` | 200 off-domain terms, zero overlap | Negative control |
| `hard-negative-200` | 200 phonetically/orthographically close terms | Insertion/loss sensitivity |

Budget is **200** terms where specified `[V: docs/preregistration.md §9]`. Selection never reads the reference script `[V: docs/design.md §5]`. The unit of analysis is the (utterance, term) pair clustered by call `[V: docs/preregistration.md §3]`.

Minimum intake is **4 calls**; **20 calls** is the smallest design with a defensible minimum detectable effect (~20pp real-term recall) `[V: docs/real-audio-intake.md; docs/preregistration.md §5]`. Each call carries **5 utterances** in the committed corpus `[V: docs/preregistration.md §5]`.

## 2. Two supply paths

### A. Customer-supplied audio

The customer records or exports the calls and supplies the reference text, consent, and PII status. LexiForge runs the harness on the customer's infrastructure or on a transfer approved by the customer. Only aggregate metrics and redacted examples leave `[V: docs/real-audio-intake.md]`.

Use this path when the result will be described as **customer evidence**. The synthetic caveat in this document then does not apply to the audio, but the small-n and reference-quality limits still do.

### B. LexiForge-supplied (synthetic)

LexiForge reads the committed scripts with TTS, applies the telephony chain, and runs the same four arms. This is **internal harness validation only** `[V: docs/keyterm-health-poc.md §3]`. It proves plumbing, selection, scoring, and reporting; it does not measure customer behaviour. Every report from this path keeps the synthetic and circularity disclosure.

No real customer audio is required for path B, and no path-B result may be shown as a customer result.

## 3. Required per-call package

| Item | Required | Supplied by | Notes |
|---|---|---|---|
| `call_id` | Yes | Intake owner | Unique within the manifest; duplicate is an error |
| `audio` | Yes | Customer (A) / LexiForge (B) | WAV/MP3/M4A/FLAC, 8 kHz or higher preferred `[V: docs/real-audio-intake.md]` |
| `reference` **xor** `reference_text` | Yes | Customer (A) / scripts (B) | Exactly one per call; both or neither is an error `[V: docs/real-audio-intake.md]` |
| `call_type` | Yes | Customer | e.g. `mandate_fail`, `upi_failed`, `collections` |
| `utterances` | Yes | Customer | Number of reference turns |
| `mismatched_domain` | Optional | Customer | Off-domain pool for the negative control |
| `consent_ref` | Yes | Customer | Pointer to the signed or recorded consent |
| `pii_status` | Yes | Customer | `redacted` or an explicit approval to process unredacted audio `[I: intake convention; no repo schema yet]` |

`must_have[]` is optional and only available where the manifest schema supports it; it does not replace `reference`.

A manifest is accepted only when every row above is complete for every call. Validate before any paid job is submitted:

```bash
python scripts/run_keyterm_study.py manifest.json --glossary data/glossary.json --out-dir runs
```

That command is a **dry run** and uses no credits `[V: docs/real-audio-intake.md]`. Add `--execute` only after consent and PII gates pass.

## 4. Consent and PII gates

No audio enters the harness until both gates are recorded against the call.

**Consent must cover all six uses** `[V: docs/recording-protocol.md §7]`:

1. Recording.
2. Evaluation / ASR scoring.
3. Public demo publication of short clips.
4. Storage and retention.
5. Withdrawal before the stated freeze.
6. No PII in metadata or filenames beyond assigned speaker IDs.

**PII must be one of:**

- `redacted` — every class masked by `lexiforge/privacy.py` removed before handoff; or
- `approved` — written customer approval to process unredacted audio, with the approval referenced in `consent_ref`.

`unknown`, `pending`, or a blank field blocks the call. Do not infer consent from possession of the audio.

The aggregate-only export rule applies on both paths: only metrics, redacted examples, and provenance leave the customer boundary `[V: docs/real-audio-intake.md]`.

## 5. Per-call effort estimate

These are planning estimates, **not a time study** `[I]`. They exclude the customer's own call-recording time and exclude waiting on consent.

### Customer-supplied audio

| Step | Minutes per call | Tag |
|---|---:|---|
| Retrieve and check consent evidence | 10 | `[I]` |
| PII review / redaction | 10 | `[I]` |
| Reference verification against audio | 10 | `[I]` |
| Manifest entry + QC | 5 | `[I]` |
| **Total** | **35** | `[I]` |

At 35 min/call `[I]`: a 4-call intake is **~2.3 h** `[I]`; a 20-call intake is **~11.7 h** `[I]`.

### LexiForge-supplied (synthetic)

| Step | Minutes per call | Tag |
|---|---:|---|
| Script check / call assembly | 5 | `[I]` |
| TTS render + telephony processing | 5 | `[I]` |
| Reference reconciliation + QC | 5 | `[I]` |
| **Total** | **15** | `[I]` |

At 15 min/call `[I]`: a 4-call synthetic run is **~1 h** `[I]`; a 20-call run is **~5 h** `[I]`.

Human effort, not STT spend, is the binding cost `[V: docs/design.md §10]`. Compute pricing is separate — see [`pricing.md`](pricing.md).

## 6. Intake procedure

1. **Collect** — audio, reference, metadata, consent reference, PII status.
2. **Screen** — reject any call with missing consent, unresolved PII, no reference, or a duplicate `call_id`.
3. **Validate** — dry-run the study runner; confirm every call plans without a missing term or file.
4. **Reconcile** — where audio and reference disagree, audio wins `[V: docs/preregistration.md §3]`; record the deviation.
5. **Freeze** — hash the audio, manifest, and glossary; record `CANON_VERSION` and the context hash before execution `[V: docs/design.md §5]`.
6. **Execute** — `--execute` only after steps 1–5 pass; log credits after the batch.
7. **Report** — per-arm metrics, paired deltas with 95% CIs `[V: docs/design.md §6]`, verdict `PASS | FAIL | INCONCLUSIVE`, claims register, and the synthetic/circularity disclosure where path B applies.

## 7. What this intake does not establish

- It does not turn a 4-call run into a 5pp claim. Four clusters cannot support the recall margin; the primary verdict is non-inferiority on harm, and lift is descriptive only `[V: docs/preregistration.md §5]`.
- It does not validate real-world density. The committed corpus is above real call speech at ~1.6 terms per utterance, so effect sizes read as **upper bounds under best-case form predictability** `[V: docs/design.md §9]`.
- It does not replace reference verification. Term-level labels inherit the reference transcript's quality `[V: docs/real-audio-intake.md]`.
- Path B does not become customer evidence by adding calls or by renaming the report.

## 8. Related documents

- [`real-audio-intake.md`](real-audio-intake.md) — customer audio fields and commands.
- [`recording-protocol.md`](recording-protocol.md) — consent checklist and pronunciation guide.
- [`preregistration.md`](preregistration.md) — frozen arms, metrics, verdict, and analysis freedoms.
- [`pricing.md`](pricing.md) — STT credits, rate limits, and worked 4-call / 20-call examples.
- [`keyterm-health-poc.md`](keyterm-health-poc.md) — POC phases and disclosure rules.
