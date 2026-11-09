# LexiForge — Operations Runbook

Solo builder. Deadline 2026-11-10. Cost is not the constraint; human hours are (~₹190 / 7 audio-hrs, <4% of balance).

## 1. One-command runbook

All commands run from the repository root. `make` may be absent on Windows, so
every target has a direct equivalent — the direct command is the primary form.
The recipes below use the same defaults as the direct commands; the variables on
the make line only replace the literal paths shown.

| Target | Does | Direct command (Windows) |
|---|---|---|
| `make doctor` | Verify the API key and read live constraints. Costs no credits. | `python -m lexiforge.cli doctor` |
| `make check-data` | Read-only data consistency checks (ids, sha256, assignments, docs). | `python scripts/check_data_consistency.py` |
| `make study` | Dry-run the four-arm study over `MANIFEST`. Builds plans; zero network, zero credits. | `python scripts/run_keyterm_study.py recording/manifest.template.json --glossary data/glossary.json --out-dir runs` |
| `make study-execute` | Run the study for real. Spends credits; requires a key. | `python scripts/run_keyterm_study.py recording/manifest.template.json --glossary data/glossary.json --out-dir runs --execute` |
| `make repro` | Re-score recorded transcripts, re-run H1/H2, write `runs/reproduce.json`. Zero network. | `python scripts/reproduce_study.py recording/manifest.template.json --runs-dir runs --out runs/reproduce.json` |
| `make report-page` | Render the study report to static inline-CSS HTML (no JS, no CDN). | `python scripts/build_report_page.py --report runs/gnani-bfsi-recording-1/report.json --out web/data/report/sample/index.html` |
| `make test` | Run the test suite. | `python -m pytest tests/ -q` |

`MANIFEST`, `GLOSSARY`, `RUNS`, `STUDY_ID`, `REPORT` and `REPORT_PAGE` are
overridable on the make command line, e.g.
`make study MANIFEST=recording/manifest.json`. When invoking a script directly,
substitute the same values by hand. `make repro` assumes an executed study has
already written transcripts under `RUNS`; `make report-page` reads the JSON
report named by `REPORT` (the dict `build_report` returns).

If one of the scripts above is missing, that checkout predates its merge — the
target is declared ahead of the script. Do not improvise replacement flags.

`study`, `study-execute` and `repro` need reference files next to the manifest.
The committed `recording/manifest.template.json` points at `recording/refs/`,
which is gitignored and absent on a clean checkout. Run the pack command in the
20-call dry-run block below first; it writes the references. Without them the
runner stops with `FileNotFoundError`.

### 20-call dry run (zero credits, no audio)

This is the full prepare-only pass: build the 20-call recording pack, then let
the study runner plan all four arms for every call. It does not read audio and
does not call the API.

```bash
python scripts/build_recording_pack.py --calls c00,c01,c02,c03,c04,c05,c06,c07,c08,c09,c10,c11,c12,c13,c14,c15,c16,c17,c18,c19
python scripts/run_keyterm_study.py recording/manifest.template.json --glossary data/glossary.json --out-dir runs
```

Expect `runs/gnani-bfsi-recording-1/summary.json` with `"dry_run": true` and
`"calls": 20`. The pack is a template: references and metadata are filled in,
audio paths point at `recording/audio/<call>.wav` and stay unused until human
audio is recorded. The pack is written under `recording/`, so the tracked
`recording/manifest.template.json` becomes the 20-call version and
`recording/scripts/` gains the new sheets — review that diff before committing.
When audio exists, rename the filled manifest to `recording/manifest.json`, run
`python scripts/record_check.py recording/manifest.json`, then repeat the study
command with `--execute`.

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

## 5. Measurement integrity — verify before scoring

Run on the scoring machine before the first scored run (Nov 8). Each item must pass; a failure blocks scoring rather than being noted downstream.

- [ ] **Cross-process seeding:** regenerate one seeded context (mismatched, random, padded or dilution) in a second process under a different `PYTHONHASHSEED`; the output must be byte-identical.
- [ ] **Exact budgets:** mismatched-200, oracle-200, adaptive-200, dilution and near-miss each carry exactly their stated term count. Selector underfill is reported separately and never counted as an equal-budget arm.
- [ ] **Provenance:** every scored output records `CANON_VERSION` and the matcher identity used to score it.
- [ ] **Canonicaliser/tokenizer parity:** the parity test passes on the frozen fixture set.

> Seeded contexts produced before this fix are **not** reproducible: the old fallback was salted by `PYTHONHASHSEED`, and unknown call types may map to a different alternative domain than before. Regenerate those contexts and record the new hash manifest before scoring.

## 6. Hard cutoffs

- Last recording: **Nov 4 EOD**.
- Last reference: **Nov 5** (G2: references complete + matcher frozen).
- Last API run: **Nov 7 EOD** (~287 jobs done; no new POSTs after).
- Last analysis change: **Nov 8 EOD** (G3: score + adjudicate + analyse).
- Demo freeze: **Nov 9 16:00**. Morning Nov 9 is the only buffer. Submit Nov 10.

## 7. Scope-cut order

Cut strictly in this order; never skip ahead:

1. near-miss arm → 2. dilution arm → 3. sweep-50 → 4. sweep-5.

Core confirmatory set (baseline, mismatched-200, oracle-200, oracle-minimal) + static-head-200 + random-200 + adaptive-200 are never cut. If Nov 2 slips, near-miss drops first, then dilution.

## 8. If it is all going wrong

- H1+H2 both clean → report both, Holm 0.025/0.05, positive control (`oracle-200 − mismatched-200`, large) validates pipeline.
- H2 holds, H1 inconclusive (recall null at ~90 occurrences) → claim H2 alone; H1 is inconclusive, not safety.
- Neither holds but selector/scoring mechanism works (coverage, retrieval-at-200, decoder-ignore rate sane) → mechanism-only report.
- Pipeline broken (control small, plumbing fails) → harness-only report: ledger, dedup, 8-state machine, reproducible jobs.
- Any outcome including a clean null → still a submission; a reproducible null is legitimate, differential-bias invalidation rule decides withdrawal.

## 9. Keyterm Health POC (measurement-led)

See [`docs/keyterm-health-poc.md`](keyterm-health-poc.md). All POC runs follow pre-registration ([`docs/preregistration.md`](preregistration.md)).

### POC prerequisites
- [ ] Matcher gold set ≥0.98 span precision/recall (Phase 0) — blocks trusting scores.
- [ ] Glossary coverage reported (selector must choose from full glossary, not echo scripts).
- [ ] Pre-registration frozen (arms/metrics/verdict/provenance). No changes after seeing data.

### POC config (must pin)
- [ ] `format=transcribe` and `language_code=hi-IN,en-IN` across all arms.
- [ ] Record `detected_language_code` per job/segment.
- [ ] One job per call/arm as appropriate; Batch preferred. `max_rps=1`. Score raw transcripts only.
- [ ] Selection uses baseline pass-1 transcript + metadata (never reference script).

### Phases (internal-only for synthetic)
- **Phase 0 (0 credits):** TTS client check (fallback to `edge-tts`), scope verification, matcher gold set, glossary coverage.
- **Phase 1 (internal harness validation, not for external distribution):** TTS `data/scripts/c00.json` → telephony-like (downsample to 8 kHz → add noise → G.711 μ-law encode/decode, in that order), record processing chain. 4 jobs (baseline, selected-200, mismatched-200, hard-negative-200). Log credits. Label synthetic/circularity.
- **Phase 2 (internal only, if Phase 1 cheap):** `c00–c03`, 16 requests. Descriptive paired deltas only (no p-values). Recompute MDE. Label synthetic.
- **Phase 3–4:** Service/productization only on pull per POC plan.

### POC gates
- [ ] Credits logged after every gate.
- [ ] Synthetic-audio and circularity disclosure in report if TTS/internal used.
- [ ] Verdict uses non-inferiority: recall CI lower bound ≥ −5pp and insertion CI upper bound ≤ +0.5; else `INCONCLUSIVE`/`FAIL`. Lift descriptive only.
- [ ] Claims register included (verified/inferred/unverified). **No measured results claimed** if not yet run.
- [ ] Decoder-ignore rate reported with numerator/denominator.
