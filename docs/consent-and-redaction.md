# Consent and Redaction

Two rules govern every real-audio call: **consent is required before the first
take**, and **nothing identifiable leaves the study machine**. This document is
the reference for both. The generated pack (`recording/consent.md`) carries the
signable form; `docs/recording-protocol.md` §7 covers who signs and when.

## 1. Consent scope

Each speaker signs one form covering all six uses **before** recording starts.
A take recorded without a signed form is not usable and is quarantined.

| Clause | What it authorises |
|---|---|
| Recording | Capturing the speaker's voice for this research project. |
| Evaluation use | Scoring the recordings with ASR models for the keyterm experiment. |
| Public demo | Using short clips in a public demo (cut from pilot data only). |
| Storage | Local storage of audio, references and hashes; gitignored, never committed. |
| Withdrawal | Withdrawing before the recording freeze; artefacts removed where feasible. |
| No PII | Only assigned speaker IDs appear in metadata, filenames and sidecars. |

Consent is per speaker, not per call. A replacement speaker (see
`docs/recording-protocol.md` §9) must sign the same form that day, before any
take is kept.

## 2. Withdrawal and the freeze

- Withdrawal is allowed up to the recording freeze (§7); the confirmed date is
  written into the recording log. After the freeze the analysis is fixed.
- On withdrawal, delete the affected audio and reference material where
  feasible, quarantine anything already scored, and log the decision in the
  retake/arbitration log. Do not silently drop a call from the manifest; mark
  it withdrawn and rebuild the pack.
- Nothing recorded before consent was signed enters the corpus, even if the
  speaker later consents.

## 3. Redaction

`lexiforge/privacy.py` is the single redaction implementation. It masks five
digit-shaped classes, longest-first, with stable per-document masks so repeated
values stay comparable:

| Masked class | Mask | Notes |
|---|---|---|
| Card number | `[CARD]` | 16 digits, optionally space/dash separated. |
| Phone number | `[PHONE]` | Indian mobile, optional `+91` prefix. |
| Aadhaar number | `[AADHAAR]` | 12 digits, contiguous or grouped 4-4-4. |
| Account number | `[NUMBER]` | Any remaining 9–18 digit run. |
| E-mail address | `[EMAIL]` | Local-part `@` domain. |

Deliberately **not** masked: glossary terms (`NEFT`, `UPI`, `IFSC`), amounts
shorter than nine digits, and Devanagari words. Devanagari digits are normalised
to ASCII first, so a number typed in either script hits the same rules.

Redaction is applied at the export boundary (`redact_object` over the dashboard
payload), not at capture time: the scorer needs the unredacted reference to
measure term recall.

## 4. Aggregate-only export rule

Only **aggregate metrics and redacted examples** leave the study machine:

- Allowed: per-arm recall/WER/insertions, paired deltas with CIs, term-level
  hit/miss counts, verdict, run metadata, and short examples that have passed
  `redact_object`.
- Forbidden: raw or lightly trimmed audio, unredacted reference transcripts,
  sidecar metadata carrying names or contact details, and full dashboard
  exports containing a masked-class value in cleartext.
- Audio leaves only as a hash in provenance (`audio_hashes`), never as a file,
  unless a separate publication consent covers that clip.

When in doubt, export the aggregate and cite the hash. A reviewer must be able
to reproduce the numbers without receiving the recordings.

## 5. Checklist before a call is scored

1. [ ] Signed consent form on file; `consent_ref` set in the manifest.
2. [ ] `pii_status` set to `redacted`, or approval documented.
3. [ ] Speaker IDs only in filenames, sidecars and the manifest.
4. [ ] Export payload reviewed for the five masks above.
