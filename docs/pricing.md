# Pricing and compute cost — Keyterm Health POC

**Status:** design-phase planning model. Not a quote.  
**Date:** 2026-11-09  
**Basis:** `docs/design.md` §10 (cost, rate limit, wall clock).

> **Synthetic caveat — this is not a rate card.** The committed corpus is **synthetic: four speakers, one accent region, scripted then read aloud, ~1.6 glossary terms per utterance** (verified: `docs/design.md` §9). Per-call totals below are an internal planning model over that corpus and read as an **upper bound**, not a customer price. A customer quote requires re-measuring duration on the customer's audio and keeping this caveat attached. Never present a synthetic-audio figure as real-traffic cost.

**Number tags.** `[V]` = verified in this repository (cite given). `[I]` = inferred from an assumption or arithmetic on verified inputs; re-measure before quoting. A tag applies to the adjacent figure only.

---

## 1. Verified rate model

| Item | Value | Tag |
|---|---|---|
| STT price, REST and Batch alike | **₹27.00 (INR 27.00) per audio hour** | `[V: docs/design.md §10]` |
| Credit definition | **1 credit = ₹1 (INR 1)** | `[V: docs/design.md §10]` |
| Batch rate limit | **60 requests/minute** | `[V: docs/design.md §10]` |
| Account balance | **5,000 credits ≈ 11,100 audio minutes** | `[V: docs/design.md §10]` |
| Pre-registered full matrix | **~420 billed minutes = 7 audio hours ≈ ₹190** | `[V: docs/design.md §10]` |
| Matrix share of balance | **<4%** (₹190 of ₹5,000 = 3.8%) | `[V: <4%; I: 3.8%]` |
| Polling at 15-second intervals | **~18 requests/minute** | `[V: docs/design.md §10]` |

Useful conversions from the same rate:

- ₹27.00/audio-hour = **₹0.45 per audio minute** `[I: 27 ÷ 60]`.
- 5,000 credits at ₹27/hour = **~11,111 audio minutes** `[I: 5,000 ÷ 27 × 60]`; the design rounds this to ~11,100 `[V]`.

**Billing granularity is not stated in the repository.** The examples below assume exact proportional billing by audio duration, with no minimum charge `[I]`. If the invoice rounds up per job or applies a minimum, add that before quoting.

**Per-call duration is not stored in the repository.** The design's ~420 billed minutes over ~287 jobs implies **~1.46 min per job** `[I: 420 ÷ 287]`, rounded here to **1.5 min per call per arm** `[I]`. Script `est_s` values are shorter because they count speech only, not the billed audio file `[I]`; do not use them as a price basis.

## 2. Worked example — 4-call intake

Four calls, four arms (`baseline`, `selected-200`, `mismatched-200`, `hard-negative-200`):

| Quantity | Value | Tag |
|---|---:|---|
| Calls | 4 | `[V: docs/real-audio-intake.md]` |
| Arms per call | 4 | `[V: docs/preregistration.md §9]` |
| Jobs | 16 | `[I: 4 × 4]` |
| Billed minutes at 1.5 min/call/job | 24 | `[I: 16 × 1.5]` |
| Audio hours | 0.4 | `[I: 24 ÷ 60]` |
| STT cost | **₹10.80** | `[I: 0.4 × ₹27]` |
| Credits | **~10.8 → 11** | `[I: 1 credit = ₹1]` |
| Share of 5,000-credit balance | 0.22% | `[I: 10.8 ÷ 5,000]` |
| Minimum submission time at 60 req/min | ~16 seconds | `[I: 16 ÷ 60 min]` |

If baseline is re-submitted rather than reused as the pass-1 transcript, add one job per call: 20 jobs, 30 billed minutes, **~₹13.50** `[I]`. The committed runner includes `baseline` in the same four-arm plan, so 16 jobs is the default `[V: scripts/run_keyterm_pilot.py — ARM_NAMES]`.

## 3. Worked example — 20-call intake

Twenty calls, same four arms:

| Quantity | Value | Tag |
|---|---:|---|
| Calls | 20 | `[V: docs/preregistration.md §5]` |
| Jobs | 80 | `[I: 20 × 4]` |
| Billed minutes at 1.5 min/call/job | 120 | `[I: 80 × 1.5]` |
| Audio hours | 2.0 | `[I: 120 ÷ 60]` |
| STT cost | **₹54.00** | `[I: 2.0 × ₹27]` |
| Credits | **~54** | `[I: 1 credit = ₹1]` |
| Share of 5,000-credit balance | 1.08% | `[I: 54 ÷ 5,000]` |
| Minimum submission time at 60 req/min | ~1.3 minutes | `[I: 80 ÷ 60]` |

Adding the optional `static-200` arm makes it five arms: 100 jobs, 150 billed minutes, **~₹67.50** `[I]`.

**The pre-registered full matrix is larger than either example.** It is ~287 jobs across pass-1 selection and pass 2: ~420 billed minutes, seven audio hours, **~₹190**, and under 4% of the balance `[V: docs/design.md §10]`. The 20-call four-arm core above is ₹54 of that cost `[I]`.

## 4. Duration sensitivity

Cost is linear in billed duration. Both examples at alternative per-call durations:

| Minutes per call per arm | 4-call cost (16 jobs) | 20-call cost (80 jobs) | Tag |
|---:|---:|---:|---|
| 1.0 | ₹7.20 | ₹36.00 | `[I]` |
| **1.5 (planning default)** | **₹10.80** | **₹54.00** | `[I]` |
| 2.0 | ₹14.40 | ₹72.00 | `[I]` |
| 3.0 | ₹21.60 | ₹108.00 | `[I]` |

A 2× error in the duration assumption is a 2× error in cost `[I]`. Duration is the only input that can move the total materially at this scale.

## 5. Wall clock

Submission is not the bottleneck. At the stated **60 requests/minute** `[V]`:

- 16 jobs → ~16 seconds `[I]`.
- 80 jobs → ~1.3 minutes `[I]`.
- 287 jobs → **~4.8 minutes**, inside the five-minute submission allowance `[V: docs/design.md §10]`.

Completion time depends on server-side job parallelism, which is unstated and measured by the concurrency probe `[V: docs/design.md §10]`. Polling at 15-second intervals is ~18 requests/minute `[V]`; it is not a separate billed line.

## 6. What the model excludes

| Excluded item | Why | Tag |
|---|---|---|
| TTS generation | The ₹27/hour rate covers STT, REST, and Batch; TTS pricing is not stated | `[V: scope of design §10; I: exclusion]` |
| Retries and reruns | A re-submitted job bills its audio again | `[I]` |
| Failed-job billing | The repo does not state whether a zero-frame or rejected job bills | `[I]` |
| Storage, egress, human review | Not part of the per-audio-hour rate | `[I]` |
| Volume discounts / committed-use terms | Not stated | `[I]` |

Budget one rerun of the affected jobs at +100% of their cost if a batch must be repeated `[I]`. For a 20-call core run, that is at most **+₹54** `[I]`.

Human effort dominates the true POC cost, not STT spend `[V: docs/design.md §10]`. Per-call effort estimates are in [`poc-intake.md`](poc-intake.md) §5: **~35 min/call** for customer-supplied intake and **~15 min/call** for a synthetic run `[I]`. No blended labour rate is asserted here.

## 7. Claims discipline

- **Verified:** ₹27/audio-hour, 1 credit = ₹1, 60 req/min, 5,000 credits ≈ 11,100 minutes, ~420 billed minutes ≈ ₹190, <4% of balance, ~287 jobs inside five minutes `[V]`.
- **Inferred:** 1.5 min per call per arm, all per-example totals, credit counts, percentages, submission times, sensitivity rows, and the exclusion allowances `[I]`.
- **Unverified and not claimed:** TTS cost, failed-job billing, invoice rounding, server-side parallelism, customer-traffic duration `[I]`.

The synthetic, four-speaker, upper-bound caveat at the top of this document must travel with every figure in it.
