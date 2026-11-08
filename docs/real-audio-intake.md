# Real-audio intake — Keyterm Health study

This is the **B path**: run the four-arm pilot on real, consented calls instead of
synthetic TTS.

## What to provide

Minimum 4 calls; 20 calls is the smallest design with a defensible MDE (~20pp
real-term recall). More calls are better.

Per call:

| Item | Required | Notes |
|---|---|---|
| Audio | Yes | WAV/MP3/M4A/FLAC, 8 kHz or higher; telephony recordings preferred |
| Reference transcript | Yes | UTF-8 text; the human-verified words spoken in the call |
| `call_type` | Yes | e.g. `mandate_fail`, `upi_failed`, `collections` |
| `utterances` | Yes | Number of reference utterances/turns |
| `mismatched_domain` | Optional | Off-domain pool for the negative control |
| Consent record | Yes | A signed/recorded consent covering this use |
| PII status | Yes | Redacted, or explicit approval to process |

Do **not** send real customer audio without consent. The harness scores on the
customer's infrastructure; only aggregate metrics and redacted examples leave.

## Manifest format

```json
{
  "study_id": "gnani-bfsi-pilot",
  "calls": [
    {
      "call_id": "c01",
      "audio": "audio/c01.wav",
      "reference": "refs/c01.txt",
      "call_type": "mandate_fail",
      "utterances": 5,
      "mismatched_domain": "upi_failed"
    },
    {
      "call_id": "c02",
      "audio": "audio/c02.wav",
      "reference_text": "inline transcript when a file is inconvenient",
      "call_type": "upi_failed",
      "utterances": 4
    }
  ]
}
```

`reference` and `reference_text` are mutually exclusive per call; one is required.

## Printable recording pack

Generate the human sheets, reference transcripts and manifest in one step:

```bash
python scripts/build_recording_pack.py --calls c00,c01,c02,c03
```

Outputs `recording/README.md`, `recording/scripts/<call>.md`,
`recording/refs/<call>.txt`, `recording/manifest.template.json`, the consent
form and the QC checklist. Audio goes to `recording/audio/` (gitignored).

## Commands

Dry run first — builds plans, uses no credits:

```bash
python scripts/run_keyterm_study.py manifest.json \
  --glossary data/glossary.json \
  --out-dir runs
```

Then execute:

```bash
python scripts/run_keyterm_study.py manifest.json \
  --glossary data/glossary.json \
  --out-dir runs \
  --execute
```

The study runner calls the existing `run_pilot` once per call, selects the
treated arms from each call's **baseline pass-1 transcript**, then pools the
per-call rows into one report. Output:

```
runs/<study_id>/report.md
runs/<study_id>/summary.json
runs/<call_id>/plan.json
runs/<call_id>/report.md
```

## Report contents

- Provenance: model, `CANON_VERSION`, context hash, seed, format, language.
- Per-arm results: real/fictional/OOV recall, insertions per utterance, WER,
  decoder-ignore numerator/denominator.
- Paired deltas with 95% CIs, clustered by call.
- Term-level appendix: recovered / lost / inserted.
- Verdict: PASS / FAIL / INCONCLUSIVE under the pre-registered non-inferiority
  rule.
- Claims register and synthetic/circularity disclosure (not applicable to real
  audio, but retained for honesty).

## What real audio changes

- The synthetic TTS ceiling disappears; recall and insertions can move.
- The result becomes customer evidence, not an internal harness check.
- A null result is still useful: it says the selected 200 did not help on this
  audio, and the wrong lists did not hurt enough to detect at this n.

## What it does not fix

- Four calls cannot support a 5pp claim. The primary verdict is non-inferiority
  on harm; lift is descriptive only.
- Term-level labels still depend on the reference transcript quality.
- Real calls may need language profiles beyond `hi-IN,en-IN`.
