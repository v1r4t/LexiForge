# LexiForge — Operations Runbook

Solo builder. Deadline 2026-11-10. Cost is not the constraint; human hours are (~₹190 / 7 audio-hrs, <4% of balance).

## 1. Daily command sequence

Only `doctor` and `canon` exist. Everything else is `[PLANNED]` — do not improvise flags; implement to this order.

| Day | Step | Command |
|---|---|---|
| Oct 29 | key + probe | `lexiforge doctor` (exists); concurrency probe `[PLANNED]` |
| Oct 30 | glossary | `lexiforge glossary build` `[PLANNED]` → `data/glossary.json` |
| Oct 30 | validate | `lexiforge glossary validate` `[PLANNED]` (nonce-root Levenshtein ≥3, alias-source check: authoring/transliteration/pre-freeze only, never ASR output) |
| Oct 30 | core-200 freeze | `lexiforge core freeze` `[PLANNED]` → commit `data/core-200` equivalent; frozen, no edits after |
| Oct 30 | assignment | `lexiforge assign --seed <SEED>` `[PLANNED]` → `data/assignment.json`; must run BEFORE author sees core-200 |
| Oct 31 | scripts | `lexiforge scripts draft` `[PLANNED]` → `data/scripts/` |
| Oct 31 | validate + freeze | `lexiforge scripts validate` `[PLANNED]` (10 mechanical checks: density ~1.6/utt, mismatched zero-overlap vs pinned real+fictional list, hard-negative placement) → `git commit` freeze |
| Nov 1 | record c01–c04 | manual: `audio/c##_t##_s##_k##`, one session/call, one device, first take default, retakes quarantined |
| Nov 1–4 | references | `lexiforge refs verify` `[PLANNED]` → `refs/` + arbitration log + deviation flag/file (~3.5 min/file; see §2 gate) |
| Nov 2 | pilot | `lexiforge contexts build --conditions baseline,oracle-200,mismatched-200` `[PLANNED]` → `lexiforge run pass1 --calls c01-c04` → `lexiforge select` → `lexiforge run pass2` `[ALL PLANNED]`; cut fallback demo clip from pilot data same day |
| Nov 3–4 | record c05–c20 | prefix-balanced speaker-pair rotation; substitution: same-day guide-passing replacement or drop to 3 speakers / 18 calls, documented |
| Nov 5 | matcher freeze | `lexiforge canon` (exists) spot-checks + collision test; freeze matcher, no further canon edits |
| Nov 6–7 | runs | `lexiforge run pass1 --all` (1 job / 100 files) → `lexiforge select` (leakage test: `refs/` unreadable, output unchanged) → `lexiforge run pass2` (~286 jobs, one/call/condition); ledger key `(condition, conversation, replicate)`; poll 15 s |
| Nov 8 | score + analyse | `lexiforge score` `[PLANNED]` (frozen matcher, stratified) → adjudication sample → `lexiforge analyse` `[PLANNED]` (sign-flip permutation, Holm 0.025/0.05) |
| Nov 9 | demo | static three-screen gallery; 16:00 freeze, no exceptions |

## 2. Blind-verification gate (BLOCKING)

Verifier must confirm ALL before opening any file. Fail = stop, reassign or re-blind.

- [ ] Cannot see `contexts/` (any condition), pass outputs, or transcripts.
- [ ] Cannot see condition labels, `assignment.json` context columns, or glossary domain packs.
- [ ] Pass 1: transcribe blind from audio only. Pass 2: reconcile against script with **audio winning**; log deviation per file.
- [ ] Blind to matcher's verdict during adjudication (discordant ~150 cap + concordant 75+75, ≥35/arm baseline + adaptive).
- [ ] Record: verifier ID, file, start/end time, deviation flag in arbitration log.

## 3. Failure playbook

- **429 (no Retry-After):** jittered exponential backoff client-side. Never spin hot; 60 req/min Batch cap, polling at 15 s ≈ 18 req/min — back off, do not reduce interval.
- **504:** single retry of same `client_job_id`. Then mark failed, inspect, manual requeue — never auto-retry twice.
- **Empty transcript:** NOT an error. Accept, score as full miss, move on.
- **Truncated:** separate from empty. Flag file, check audio ≤30 s / format vs `doctor` constraints, requeue once with same `client_job_id`.
- **Expired URL:** refetch once, resume poll. If expired again, requeue job with same `client_job_id`, do not create a duplicate job.
- **Partial job:** per-call coverage gate, not global. Call passes only if all its utterances returned; otherwise the whole call is missing, not "mostly done".
- **Crash mid-run:** resume from SQLite ledger + persisted write-ahead `client_job_id` (written BEFORE POST). Never re-POST a call whose `client_job_id` already exists — the POST→ledger-write window is the one double-bill path.

## 4. G1 pilot gate (Nov 2, calls c01–c04, scripts frozen first)

Gated (all must pass):

1. [ ] Plumbing works end to end (contexts → pass1 → select → pass2 → score).
2. [ ] Baseline real-term recall 0.85–0.99 AND fictional recall 0.30–0.70. Misses clustering on letter-spelled acronyms = canonicalisation defect: fix using pass-1 (context-free) output only, before freeze.
3. [ ] Canonicalisation: ≥90% of true spans match.

Reported tripwires (not gated, record values):

- T1: per-file flip rate across 3 baseline runs; expand to 5 runs if ≥10%.
- T2: pilot directional deltas; abort analysis if H1 or H2 sign inverted.
- H2 floor rule: zero mismatched-arm insertions in c01–c04 → H2 reported as **untested at this sensitivity**; false-insertion claim carried descriptively by graded close-pair set only.

## 5. Hard cutoffs

- Last recording: **Nov 4 EOD**.
- Last reference: **Nov 5** (G2: references complete + matcher frozen).
- Last API run: **Nov 7 EOD** (~287 jobs done; no new POSTs after).
- Last analysis change: **Nov 8 EOD** (G3: score + adjudicate + analyse).
- Demo freeze: **Nov 9 16:00**. Morning Nov 9 is the only buffer. Submit Nov 10.

## 6. Scope-cut order

Cut strictly in this order; never skip ahead:

1. near-miss arm → 2. dilution arm → 3. sweep-50 → 4. sweep-5.

Core confirmatory set (baseline, mismatched-200, oracle-200, oracle-minimal) + static-head-200 + random-200 + adaptive-200 are never cut. If Nov 2 slips, near-miss drops first, then dilution.

## 7. If it is all going wrong

- H1+H2 both clean → report both, Holm 0.025/0.05, positive control (`oracle-200 − mismatched-200`, large) validates pipeline.
- H2 holds, H1 inconclusive (recall null at ~90 occurrences) → claim H2 alone; H1 is inconclusive, not safety.
- Neither holds but selector/scoring mechanism works (coverage, retrieval-at-200, decoder-ignore rate sane) → mechanism-only report.
- Pipeline broken (control small, plumbing fails) → harness-only report: ledger, dedup, 8-state machine, reproducible jobs.
- Any outcome including a clean null → still a submission; a reproducible null is legitimate, differential-bias invalidation rule decides withdrawal.
