# LexiForge — Keyterm Health for Gnani Prisma v3.0

**One line:** Gnani gives you 200 keyterm slots per call; LexiForge chooses the
200, checks them, and proves on your own calls whether they helped or hurt.

## Problem

- Prisma v3.0 accepts up to 200 `keyterms`, but the business glossary is far
  larger and changes. Someone must choose the subset — manually, and usually once.
- Vendor benchmarks show *relevant* keyterms help on public clips. They do not
  tell a customer whether a list helps on their noisy, code-mixed calls, or
  whether it degrades ordinary recognition.
- A wrong list is a silent failure: missed brand/product/scheme names break
  search, analytics and compliance; over-broad lists can displace known words.

## What we built

A Hinglish-banking **Keyterm Health service**:

1. takes a glossary, call audio, and reference transcripts;
2. selects a candidate keyterm list;
3. runs six arms on the same audio — baseline, selected, mismatched,
   hard-negative, oracle-200, static-head-200;
4. scores term recall, insertions, WER and paired deltas;
5. returns a report with an A/B verdict and provenance.

**A** = critical terms (brand, product, must-have). **B** = all-real guardrail:
keyterms must not wreck ordinary recognition.

## Evidence — synthetic 4-call pilot

| Arm | Real recall | Brand recall | Insertions / utt |
|---|---|---|---|
| baseline | 21/23 (91.3%) | 2/12 (16.7%) | 0.00 |
| selected-200 | 16/23 (69.6%) | 10/12 (83.3%) | 0.05 |
| mismatched-200 | 17/23 (73.9%) | 3/12 (25.0%) | 0.10 |
| **oracle-200** | 19/23 (82.6%) | **12/12 (100%)** | 0.10 |

Full six-arm table: `docs/pilot4-results.md`.

- **H1** (mismatched < baseline real recall): −17.5pp, p = 0.062 — not rejected.
- **H2** (mismatched > baseline insertions): +0.10/utt, p = 0.503 — not rejected.
- **Positive control:** oracle − mismatched +9.17pp, CI [0, +18.3], passes.
- At n=4 the smallest one-sided sign-flip p is 0.0625; this is descriptive only.

**Key finding:** every keyterm list lowered real recall versus baseline —
including the oracle — while brand recall moved exactly as intended
(16.7% → 83.3–100%). The trade-off is the result, not a selector bug.

## Why Gnani

Gnani sells the 200 slots and the model. LexiForge makes the 200 the right 200
and proves it on the customer's own audio: a POC accelerator, a glossary
guardrail, and a measured capability for the keyterm feature Gnani already
ships. It runs in-VPC for regulated BFSI deployments.

## Status and limits

- Working end to end: Gnani REST + Batch clients, Timbre TTS, six arms, report,
  recording pack, 20 consistent scripts, 841 tests.
- **Synthetic TTS only; no customer audio.** Internal harness validation.
- n=4 is underpowered; a 20-call run is required before any confirmatory claim.
- Batch queue instability observed; REST with chunking is the reliable transport.
- WER is format-sensitive and not quoted as recognition quality.

## Links

- Repo: `https://github.com/v1r4t/LexiForge`
- Pitch PDF: `PITCH.pdf` · Detail: `docs/pilot4-results.md`
- Design: `docs/design.md` · Pre-registration: `docs/preregistration.md`
- Real-audio intake: `docs/real-audio-intake.md`
