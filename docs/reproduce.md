# Reproducing a study run offline

`scripts/reproduce_study.py` rebuilds a study result from the transcripts of a
previous run. It reads the manifest, the glossary and every stored per-arm
transcript, re-scores them with the frozen matcher, and re-runs the
pre-registered H1/H2 analysis. It makes **no network calls**: scores come only
from text, so a run can be reproduced on a laptop with `DEMO_MODE=precomputed`
and no API key.

Reproduction is not a re-run of the study. It proves that the reported numbers
follow from the stored transcripts and the recorded glossary, which is why the
recorded `summary.json` verdict is compared rather than trusted.

## Inputs

| Input | Required | Notes |
|---|---|---|
| `manifest` | Yes | The intake manifest used for the original run |
| `--glossary` | Yes (default `data/glossary.json`) | Must be the glossary the run was scored with |
| `runs/<call_id>/<arm>.transcript.json` | Yes | P01 per-arm transcripts, including `text` and `canon_version` |
| `runs/<call_id>/plan.json` | Optional | Declares the expected arms; otherwise all four arms are required |
| `runs/<study_id>/summary.json` | Optional | Only its `verdict` is used, as a comparison target |

Transcripts are read with `lexiforge.score.store.read_arm_transcript` when that
module is available; otherwise the same UTF-8 JSON is read directly. A
transcript that contains a `reference` key is invalid for reproduction.

## Command

```powershell
python scripts/reproduce_study.py runs/manifest.json `
  --runs-dir runs `
  --glossary data/glossary.json `
  --out runs/reproduce.json
```

POSIX equivalent:

```bash
python scripts/reproduce_study.py runs/manifest.json \
  --runs-dir runs \
  --glossary data/glossary.json \
  --out runs/reproduce.json
```

The manifest path, runs directory, glossary and output path are all explicit;
nothing is inferred from the working directory except the glossary default.

## Output

`reproduce.json` is UTF-8 with `ensure_ascii=False` and sorted keys:

| Key | Meaning |
|---|---|
| `study_id` | Manifest study id |
| `inputs.manifest` / `inputs.glossary` | Path and sha256 of each input |
| `inputs.transcripts` | `<call_id>/<arm>` → path and sha256 for every transcript |
| `canon_version` | `lexiforge.canon.CANON_VERSION` used to re-score |
| `transcript_canon_versions` | Canon versions stamped on the stored transcripts |
| `per_arm` | Re-scored per-arm summary (recall counts, insertions, WER) |
| `deltas` | Paired deltas and 95% CIs from the re-scored rows |
| `verdict` | Recomputed `PASS` / `FAIL` / `INCONCLUSIVE` |
| `recorded_verdict` | Verdict read from `summary.json` (may be `null`) |
| `matches_summary` | `true` only when the recomputed verdict equals the recorded one |
| `n_calls` | Observed paired calls, never the planned n |
| `analysis` | H1/H2, Holm, positive control, MDE and claim ladder |
| `analysis_source` | `preregistered` when P09's module is present, else `local-fallback` |

The glossary sha256 and `canon_version` are recorded together. If the
benchmark, glossary or matcher ruleset changes, a re-score under the new
glossary or canon version is a different measurement; keep the original inputs
with the original artifact.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | `reproduce.json` written; verdict may match or differ from the summary |
| `2` | A required per-arm transcript is missing; nothing is written |

Exit `2` names the call and arm, so a partially merged run is easy to repair:
restore the transcript or remove the call from the manifest, never invent text.

## Tamper detection

The stored `summary.json` verdict is not evidence. The recomputed verdict is
derived from the transcripts and the glossary; `matches_summary` is `false`
whenever a transcript was edited, an arm was swapped, or the recorded verdict
was changed by hand. The per-transcript sha256 entries in `inputs` make the
edits visible even when the verdict happens to be unchanged.

A mismatch is a stop-and-review signal, not a script failure. Re-run the study
from the original audio if the stored artifacts disagree with the report.

## Limits

- Reproduction cannot recover audio that no longer exists; it only re-scores
  text.
- The reference transcript is still the ground truth. A wrong reference
  reproduces a wrong result consistently.
- With fewer than two paired calls the recomputed verdict is `INCONCLUSIVE`;
  reproduction does not make a four-call run support a recall-margin claim.
- The analysis fallback is used only while P09's pre-registered module is
  absent. Once it lands, the same command runs the pre-registered analysis and
  labels the source `preregistered`.
