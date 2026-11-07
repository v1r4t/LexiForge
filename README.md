# LexiForge

A vocabulary-budget risk harness for Gnani Prisma v3.0 on Hinglish banking speech.

**Question:** you get 200 keyterm slots per call and your glossary has 2,000. A fixed list is stale for most calls — so what does it cost when the list is wrong?

## What this tests

Two confirmatory hypotheses, both pre-registered in the negative direction:

- **H1** — an irrelevant list costs recognized words: `mismatched-200 < baseline` on real terms the model already knows (`NEFT`, `UPI`, `KYC`, `IFSC`).
- **H2** — an irrelevant list invents words: `mismatched-200 > baseline` in glossary-term insertions per utterance.

The benefit of a *relevant* list is a positive control, not a claim. If it does not appear, the pipeline is broken.

## What this does not claim

It does not show that a static list causes harm — that is reported separately. Mismatched-200 is a worst case, a fully irrelevant list, not a typical deployment.

> **Corpus disclosure.** This is a synthetic Hinglish banking-call corpus — four volunteers, scripted and read aloud, fictional brand names, no real customer data. Results are upper-bound measurements on clean read speech with an artificially raised term density, and must not be read as real contact-centre evidence.

## Status

Design approved 2026-10-29. Deadline 2026-11-10.

- Design: [`docs/design.md`](docs/design.md)
- Keyterm Health POC: [`docs/keyterm-health-poc.md`](docs/keyterm-health-poc.md) (measurement-led, pre-registered, internal-only Phases 1-2 synthetic; no measured results claimed)
- Pre-registration: [`docs/preregistration.md`](docs/preregistration.md)
- Notes: [`docs/notes/`](docs/notes/)

### Implementation state

| Area | State |
|---|---|
| Canonicalisation + matcher | frozen (`matcher-v1.0`), collision-tested |
| Truncated-term alignment / insertion rule | implemented, tested |
| Selector `S = 0.55·Lex + 0.25·Phon + 0.20·Prior` | implemented, leakage-guarded |
| Job ledger + 8-state runner | implemented (SQLite, write-ahead ids) |
| Prisma v3.0 batch client | implemented (sync + bounded-concurrency async, typed errors) |
| Runner ↔ Prisma wiring | `PrismaBackend` implements the runner interface (create+start, wait) |
| Cluster-aware inference | implemented (sign-flip, Holm, wild bootstrap-t) |
| Glossary / core-200 / assignment data | generated and committed |
| Dashboard | API + React build; sample data is labelled as sample |
| Export redaction | phone / card / Aadhaar / account / e-mail masked by default |
| Recorded audio, references, scored runs | **not in this repo** (gitignored for consent) |

Nothing in this repository contains measured results yet. `web/data/sample/`
is a hand-written placeholder and the UI banners it as such.

Stack: Python 3.11, SQLite, FastAPI, React + Vite + Tailwind, ffmpeg.

## Install

```bash
pip install -e ".[dev]"
```

Python 3.10+ works; CI targets 3.11.

## CLI

```bash
python -m lexiforge.cli --help

lexiforge info                     # component + matcher status
lexiforge doctor                   # check the API key, costs no credits
lexiforge canon "NEFT"             # print the frozen matching key

lexiforge optimize \
  --glossary data/glossary.json \
  --hypothesis "mera NEFT transfer fail ho gaya" \
  --call-type upi_failed --max-terms 200 --output context.json

lexiforge validate job_config.json # validate a batch job config
lexiforge export-web               # build web/data from scored transcripts
```

All CLI output is ASCII so it runs on a default Windows console (cp1252).

## Dashboard

The dashboard is a FastAPI service plus a React build. Both are needed: the API
serves the JSON, the build is mounted at `/`.

```bash
# 1. build the front end (once, and after changing web/frontend)
cd web/frontend && npm install && npm run build && cd ../..

# 2. serve API + dashboard on http://127.0.0.1:8000
uvicorn web.api:app --host 127.0.0.1 --port 8000
```

Or `make run-dev` (builds then serves).

Data resolution, in order:

1. `$LEXIFORGE_WEB_DATA` if set.
2. `web/data/` when it contains `calls.json` (measured export).
3. `web/data/sample/` — the labelled placeholder set.

Files are re-read when their mtime changes, so regenerating results does not
need a restart (`POST /reload` forces it).

Endpoints: `/health`, `/meta`, `/calls`, `/calls/{id}/transcripts`,
`/calls/{id}/terms`, `/calls/{id}/audio`, `/results`, `/demo/config`,
`POST /reload`.

Audio is optional: `/calls/{id}/audio` serves `<LEXIFORGE_AUDIO_DIR>/<call_id>.{wav,mp3,m4a,flac,ogg}`
(default directory `audio/`, which is gitignored). The player only renders when
a recording actually resolves.

The call page shows two views: token chips per condition, and an alignment to
baseline (LCS diff marking lost and invented words).

Without a built front end the API still runs; `/` returns a 503 that names the
missing build step instead of a bare 404.

### Sample vs measured

`web/data/sample/results.json` carries `"is_sample": true` and every contrast is
marked `"verdict": "sample"`. `/meta` reports `is_sample` and the UI shows a
persistent amber banner. Replace it with measured output via:

```bash
lexiforge export-web --transcripts transcripts --refs refs --out web/data
```

The exporter computes recalls with the frozen matcher and emits **descriptive**
paired differences only. It never writes p-values — inference stays in
`lexiforge.analysis.inference`.

Every string it writes is redacted by default (`lexiforge/privacy.py`): phone
numbers, card numbers, Aadhaar numbers, account numbers and e-mail addresses
become stable masks. Scoring runs on unredacted text, so masking never changes
a recall figure. Pass `--no-redact` only for data you are allowed to publish;
`demo_config.json` records which mode was used and how many values were masked.

## Tracing

Spans are kept in a bounded in-process ring. Point `LEXIFORGE_TRACE_FILE` at a
path to also append one JSON object per span (name, attributes, duration, error):

```bash
LEXIFORGE_TRACE_FILE=runs/spans.jsonl lexiforge export-web
```

There is no OpenTelemetry exporter; `lexiforge info` reports observability as
`partial` for that reason.

## Containers

```bash
docker build -t lexiforge:latest .
docker run --rm -p 8000:8000 lexiforge:latest
```

The image builds the front end in a Node stage and serves it from the Python
stage. `DEMO_MODE=precomputed` (the default) disables every outbound call from
the dashboard process.

## Tests

```bash
python -m pytest tests/ -q      # 466 tests
make test-cov                   # with coverage
```

## Layout

```
lexiforge/
  canon.py            frozen canonicalisation
  ledger.py           SQLite job ledger (write-ahead client ids)
  runner.py           8-state orchestration
  api/                Prisma v3.0 clients (batch, typed errors, async helpers)
  glossary/           generation, validation, core-200, assignment
  select/             BM25 + Hinglish phonetics + prior, MMR
  score/              alignment, matching, metrics
  analysis/           permutation tests, Holm, bootstrap
  optimizer/          per-call context selection
  observability/      logging, metrics, in-process spans
  plugins/            ASR backend registry
  cli.py              command line
web/
  api.py              dashboard API
  data/sample/        labelled placeholder dataset
  frontend/           React + Vite + Tailwind dashboard
scripts/
  build_data.py       regenerate glossary/core-200/assignment
  export_web_data.py  transcripts + refs -> dashboard JSON
data/                 committed glossary, core-200, assignment, scripts
```

## Known gaps

- The container image was **not built on this machine** (no Docker daemon
  available). Each stage was verified separately instead: `npm ci` + `npm run
  build` from a clean checkout of the lock file produces the same bundle
  hashes, and `pip wheel .` builds a wheel containing every package. Treat the
  first `docker build` on a real host as unproven until it runs.
- Tracing is in-process only (bounded span deque). There is no OpenTelemetry
  export; `lexiforge info` reports observability as `partial` for that reason.
- Audio, references and transcripts are not committed, so a fresh clone cannot
  reproduce the experiment — only the harness.
- `ruff` gates on `E4`, `E7`, `E9`, `F`, `I` only. The modernization rule sets
  are intentionally off; enabling them would rewrite code outside this work.

## Checks

```bash
python -m pytest tests/ -q     # 466 tests
ruff check lexiforge tests web scripts
```

CI also runs the suite twice on Python 3.11, once with `PYTHONHASHSEED=0` and
once with `PYTHONHASHSEED=1`, so hash-order nondeterminism in generated contexts
cannot pass silently. A separate job builds a wheel with
`python -m pip wheel . --no-deps`.
