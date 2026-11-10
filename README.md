# LexiForge

**A keyterm-risk harness and measurement service for Gnani Prisma v3.0 on
Hinglish banking calls.**

You get 200 keyterm slots per call. Your glossary has hundreds or thousands of
terms. Someone has to choose the 200 — and today there is no repeatable way to
know whether that list helped, hurt, or did nothing on your own calls.

LexiForge measures it.

> **Scope and honesty.** Hinglish banking speech only. Current evidence is a
> synthetic TTS pilot, not customer recordings. Every result in this repo is
> internal harness validation until real, consented audio is run.

---

## The problem

- Gnani Prisma v3.0 accepts up to 200 `keyterms` per request, plus `topic`,
  `speaker_names`, and a small substitution map.
- Enterprise glossaries are larger, stale, and owned by the business — not the
  ASR vendor.
- Vendor benchmarks show that *relevant* keyterms help on public clips. They do
  not tell a customer whether a candidate list helps on their noisy,
  code-mixed calls, or whether it quietly degrades ordinary recognition.
- A wrong list can silently cost real terms or add unspoken ones. Missed brand
  names break search, analytics, and compliance.

## What LexiForge does

Given a glossary, call audio, and reference transcripts, it:

1. selects a candidate keyterm list for each call;
2. runs controlled arms on the **same audio**;
3. scores term-level recall, insertions, WER, and paired deltas;
4. returns a **Keyterm Health Report** with an A/B verdict and provenance.

### The arms

| Arm | What it is |
|---|---|
| `baseline` | No keyterms |
| `selected-200` | Selector output (natural size by default; optional padding) |
| `mismatched-200` | 200 off-domain terms (negative control) |
| `hard-negative-200` | 200 phonetically close terms |
| `oracle-200` | Expected terms + padding (positive control) |
| `static-head-200` | One fixed core-200 list (secondary control) |

### The endpoints

- **A — critical terms:** brand, product, scheme, and customer must-have terms.
- **B — all real terms:** non-inferiority guardrail. Keyterms must not wreck
  ordinary recognition.

A pass needs A to improve **and** B to stay within the agreed harm margin.

---

## Current result — synthetic, 4 calls

`c00–c03`, 5 turns each, TTS voices, `format=transliterate`, six arms.

| Arm | Real recall | Brand recall | Insertions / utt | WER |
|---|---|---|---|---|
| baseline | 21/23 (91.3%) | 2/12 (16.7%) | 0.00 | 27.2% |
| selected-200 (brand-only) | 16/23 (69.6%) | 10/12 (83.3%) | 0.05 | 41.8% |
| mismatched-200 | 17/23 (73.9%) | 3/12 (25.0%) | 0.10 | 39.2% |
| hard-negative-200 | 18/23 (78.3%) | 2/12 (16.7%) | 0.20 | 41.3% |
| **oracle-200** | 19/23 (82.6%) | **12/12 (100%)** | 0.10 | 37.0% |
| static-head-200 | 17/23 (73.9%) | 6/12 (50.0%) | 0.00 | 34.1% |

Pre-registered H1/H2 (`mismatched − baseline`):

- **H1** real recall **−17.5pp**, p = 0.062 — **not rejected**.
- **H2** insertions **+0.10/utterance**, p = 0.503 — **not rejected**.
- **Positive control** oracle − mismatched **+9.17pp**, CI [0.0, +18.3], passes.
- **Claim ladder:** mechanism only.

At n=4 the smallest attainable one-sided sign-flip p is **0.0625**, so
rejection is impossible. The direction is consistent; the sample is not.

**The key finding:** every keyterm list lowered real-term recall versus
baseline — including the oracle — while brand recall moved exactly as intended
(16.7% → 83.3–100%). The trade-off is the result, not a selector bug.

Full write-up: [`docs/pilot4-results.md`](docs/pilot4-results.md).

---

## Install

```bash
pip install -e ".[dev]"
```

Python 3.10+ works; CI targets 3.11. `ffmpeg` is used for audio conversion.

```bash
python -m pytest tests/ -q     # 841 tests
ruff check lexiforge tests web scripts
```

## Quick start

```bash
python -m lexiforge.cli doctor      # verify the Gnani key; no credits
python -m lexiforge.cli info        # component + matcher status
python -m lexiforge.cli canon NEFT  # print the frozen matching key
```

`.env` (gitignored):

```text
GNANI_API_KEY=...
GNANI_BASE_URL=https://api.vachana.ai
```

## Run a Keyterm Health study

### 1. Build or record the calls

```bash
# printable 20-call pack: sheets, references, manifest, consent, QC
python scripts/build_recording_pack.py

# synthetic fallback (internal validation only)
python scripts/synthesize_recording_pack.py --calls c00,c01,c02,c03
```

Human recordings go in `recording/audio/<call>.wav`. Read the sheets exactly
as written; the references in `recording/refs/` are the ground truth.

### 2. Validate the intake

```bash
python scripts/record_check.py recording/manifest.template.json
```

Checks duration, sample rate, channels, clipping, DC offset, silence, duplicate
IDs, and reference transcripts. `--strict` makes QC warnings fail.

### 3. Run the arms

```bash
# free dry-run: builds the arm plan and writes plan.json
python scripts/run_keyterm_study.py recording/manifest.pilot4.json \
  --glossary data/glossary.json

# execute over REST (the Batch queue has been stalling)
python scripts/run_keyterm_study.py recording/manifest.pilot4.json \
  --glossary data/glossary.json --out-dir runs \
  --execute --rest --selected-natural --critical-only \
  --format transliterate \
  --arms baseline,selected-200,mismatched-200,hard-negative-200,oracle-200,static-head-200
```

Outputs:

```
runs/<study_id>/report.md          Keyterm Health Report
runs/<study_id>/summary.json       verdict, failures, per-call path
runs/<study_id>/per_call.json      per-call aggregates
runs/<study_id>/preregistered.json optional H1/H2 analysis
runs/<call>/<arm>.transcript.json  persisted transcripts
```

### 4. Pre-registered analysis

```bash
python scripts/analyse_preregistered.py runs/gnani-bfsi-pilot4/per_call.json \
  --out runs/gnani-bfsi-pilot4/preregistered.json
```

## Reproduce and inspect

```bash
python scripts/reproduce_study.py --help   # offline re-score + verdict check
python scripts/run_list_sweep.py --budgets 5,50,200
python scripts/build_report_page.py --help # static HTML report page
python scripts/check_data_consistency.py   # data/script/glossary gates
```

See [`docs/reproduce.md`](docs/reproduce.md) and the
[`Makefile`](Makefile) targets: `check-data`, `study`, `study-execute`,
`repro`, `report-page`.

## CLI

```bash
python -m lexiforge.cli --help

lexiforge info
lexiforge doctor
lexiforge canon "NEFT"
lexiforge optimize --glossary data/glossary.json \
  --hypothesis "mera NEFT transfer fail ho gaya" \
  --call-type upi_failed --max-terms 200 --output context.json
lexiforge validate job_config.json
lexiforge export-web
```

All CLI output is ASCII for Windows consoles.

## Dashboard

FastAPI API + React/Vite/Tailwind build.

```bash
cd web/frontend && npm ci && npm run build && cd ../..
uvicorn web.api:app --host 127.0.0.1 --port 8000
# or: make run-dev
```

Data resolution: `$LEXIFORGE_WEB_DATA` → `web/data/` (measured) →
`web/data/sample/` (labelled placeholder). `/meta` reports `is_sample`; the UI
shows an amber banner. Endpoints: `/health`, `/meta`, `/calls`,
`/calls/{id}/transcripts`, `/calls/{id}/terms`, `/calls/{id}/audio`,
`/results`, `/demo/config`, `POST /reload`.

Exports are redacted by default (`lexiforge/privacy.py`): phone, card, Aadhaar,
account, e-mail. Scoring runs on unredacted text, so masking never changes a
recall figure.

A static report page is also generated:

```bash
python scripts/build_report_page.py --help
# committed example: web/data/report/sample/index.html
```

## Architecture

```text
lexiforge/
  canon.py              frozen canonicalisation (matcher-v1.0)
  ledger.py             SQLite job ledger, write-ahead client ids
  runner.py             8-state orchestration
  api/                  Prisma clients: batch, REST fallback, admin, validator
  audio/                8 kHz telephony, G.711 mu-law, noise, WAV I/O
  tts/                  Gnani Timbre client (Poorvi / Deepak)
  contexts/             arms, oracle-200, static-head-200, mismatch, hard negatives
  select/               BM25 + HING-SKEL phonetics + priors, MMR
  score/                frozen matcher, alignment, metrics, transcript store,
                        term diff, presence sensitivity, alias audit
  analysis/             permutation, Holm, bootstrap, pre-registered H1/H2
  report/               Keyterm Health report, provenance, claims register
  study/                validated manifest schema
  glossary/             generation, validation, core-200, assignment
  optimizer/            per-call context selection
  observability/        logging, metrics, in-process spans
  plugins/              ASR backend registry

scripts/
  build_data.py                 regenerate glossary/core-200/assignment
  build_pilot_scripts.py        regenerate c00-c19 from assignment + glossary
  build_recording_pack.py       printable sheets, refs, manifest, consent, QC
  synthesize_recording_pack.py  TTS fallback for the pack
  record_check.py               audio/manifest QC
  run_keyterm_pilot.py          one call, all arms
  run_keyterm_study.py          multi-call study, resume, report
  analyse_preregistered.py      H1/H2 + Holm + positive control
  run_list_sweep.py             list-size dose response
  reproduce_study.py            offline re-score and verdict check
  build_report_page.py          static HTML report
  check_data_consistency.py     CI data gates
  export_web_data.py            transcripts + refs -> dashboard JSON

data/                    1,000-term glossary, core-200, assignment, 20 scripts
recording/               pack: sheets, refs, manifest, consent, QC
web/                     FastAPI dashboard + React frontend
```

## Data

- `data/glossary.json` — 1,000 terms (180 real, 820 fictional).
- `data/core200.json` — frozen 200-term static list.
- `data/assignment.json` — per-call term assignment.
- `data/scripts/c00–c19.json` — 20 consistent call scripts, each with expected
  real/fictional IDs.
- `c00–c03` are the frozen pilot calls; `c04–c19` regenerate identically from
  the assignment.

## Tests and checks

```bash
python -m pytest tests/ -q          # 841 tests
ruff check lexiforge tests web scripts
python scripts/check_data_consistency.py
python scripts/eval_matcher_gold.py # 47 hand-labelled cases, >=0.98 gate
```

CI runs the suite on Python 3.11 under `PYTHONHASHSEED=0` and `=1`, builds the
wheel, and builds the frontend.

## Known gaps

- **No real customer audio.** The measured result is synthetic TTS; treat it as
  harness validation, not contact-centre evidence.
- **n=4 is underpowered.** The smallest attainable one-sided p is 0.0625; H1/H2
  cannot reject. A 20-call run is required.
- **Every keyterm list lowered real recall in the pilot**, including the oracle.
  Whether that is ASR bias or transliteration/alias drift is the next experiment.
- **Batch queue instability.** Two fresh jobs sat `QUEUED` for 30+ minutes; the
  REST client with chunking is the reliable path for short calls.
- **WER is format-sensitive** (27–42% in the pilot). Do not quote it as
  recognition quality.
- **Glossary size** is 1,000, not the 2,000 assumed in early notes; the 20
  scripts are consistent with the committed assignment.
- **Dashboard sample data** is a labelled placeholder; the static report page is
  the portable artifact.
- **Docker build is unverified** on a host with a daemon.
- **Tracing is in-process only**; no OpenTelemetry exporter.
- **Selector composition is not final.** Brand-only selection wins brand recall
  but costs real recall; brand + must-have real terms is the untested next step.

## Docs

- [Design](docs/design.md)
- [Pre-registration](docs/preregistration.md) ·
  [Amendment 1](docs/preregistration-amendment-1.md)
- [Keyterm Health POC](docs/keyterm-health-poc.md)
- [Pilot 4 result](docs/pilot4-results.md)
- [Report template](docs/keyterm-health-report-template.md)
- [Real-audio intake](docs/real-audio-intake.md)
- [Recording protocol](docs/recording-protocol.md) ·
  [Consent and redaction](docs/consent-and-redaction.md)
- [POC intake](docs/poc-intake.md) · [Pricing](docs/pricing.md)
- [Reproduce](docs/reproduce.md) · [Runbook](docs/runbook.md)
- [Notes](docs/notes/)

## Status

Research harness and POC-ready measurement service. The engineering is
complete enough to run a real study; the scientific claim is still pending real
Hinglish audio and a 20-call analysis.
