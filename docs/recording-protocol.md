# Recording Protocol

## 1. Session setup

- **One session per call.** Record each of the 20 calls in its own recording session. Do not batch multiple calls into a single continuous recording session.
- **Both speakers present.** Both the agent (AGT) and customer (CUS) must be physically present for the entire call. The alternating AGT/CUS/AGT/CUS/AGT structure requires both speakers for every utterance.
- **One device, one room.** All audio for a call must be captured on a single recording device in a single, consistent room. This is non-negotiable.
- **Why:** Splitting across devices confounds the acoustic channel with the speaker identity. Cross-device capture introduces channel variation that cannot be cleanly separated from speaker effects, which would invalidate the controlled comparisons central to this experiment.

## 2. Pronunciation guide format

The pronunciation guide must contain, for any terms the speakers might be uncertain about, the following fields:

| Field | Description |
|---|---|
| Written form | The canonical written form as it appears in the glossary/script. |
| Syllables | A syllabic breakdown of the term. |
| Stress | Primary (and secondary if applicable) stress marking. |
| Reference recording path | Path to a short reference recording (e.g., `refs/pronunciation/<term_id>.wav`) to consult for consistency. |

**Note:** The guide exists for consistency, but there is **NO rehearsal drill**. The default is the **first take**. Speakers should not run practice passes through the full script.

## 3. Delivery rules

- **Conversational rate:** Speak at a natural, conversational pace. Do not slow down artificially for the microphone.
- **No spelling out unless the script says so:** Only spell terms if the script explicitly instructs spelling. Do not default to letter-by-letter reading.
- **No hyper-articulation:** Avoid over-enunciating, exaggerating consonants/vowels, or speaking "for ASR". 
- **Natural fillers:** Use natural, unscripted fillers sparingly as they would occur in conversation (where they fit naturally). Do not add them gratuitously.

**Rationale:** Hyper-articulation suppresses the natural confusability between terms that the experiment depends on. The goal is to measure how context affects recognition on realistic, conversational speech, not hyper-clear speech.

## 4. Retake policy

- **Max 3 per turn:** Each utterance/turn may be retaken at most 3 times total. If unintelligible after 3 attempts, the session lead must document the issue per the dropout rule (§9) and decide whether the call can proceed.
- **Rejected takes quarantined not deleted:** Any take that is rejected (due to error, misread, unintelligibility, or deviation) must be moved to a quarantine location (e.g., `audio/quarantine/`) and never deleted. Quarantined takes must remain traceable.
- **Retake log columns:** Every retake must be logged with the following columns:
  | Column | Description |
  |---|---|
  | `call_id` | Call identifier (e.g., c01) |
  | `turn_id` | Turn/utterance index in the AGT/CUS/AGT/CUS/AGT sequence |
  | `take_number` | Take number attempted (1-based; includes rejected) |
  | `reason` | Reason for retake/rejection (e.g., misread, unintelligible target term, cough/noise, deviation) |
  | `decision` | `keep`, `reject-quarantine`, or `abandon-turn` |
  | `recorder` | Initials of person recording |
  | `timestamp` | ISO 8601 timestamp of decision |

## 5. File naming and sidecar JSON schema

**File naming:** `c##_t##_s##_k##`  
- `c##` — call number (01-20)  
- `t##` — turn/utterance number within call  
- `s##` — speaker (e.g., 01=AGT, 02=CUS, assigned per call pair)  
- `k##` — take number (01 for first kept take; increments only for kept takes, or as logged)

Rejected takes do **not** follow the "kept" naming for final corpus placement — they go to quarantine with traceable references in the retake log.

**Sidecar JSON schema (required for each kept audio file):**
```json
{
  "call_id": "c01",
  "pair_id": "AB",
  "turn_id": 1,
  "speaker_role": "AGT|CUS",
  "speaker_id": "S1",
  "take_kept": 1,
  "script_path": "data/scripts/c01.json",
  "device_id": "rec-01",
  "room_id": "room-01",
  "recorded_at": "2026-11-01T10:23:45Z",
  "guide_used": true,
  "rehearsal_drill": false,
  "first_take_default": true,
  "qc_passed": false,
  "notes": ""
}
```

All fields are required. `rehearsal_drill` must always be `false`. `first_take_default` must be `true` unless explicitly overridden per the retake policy with logged justification.

## 6. Recording order

The **six speaker pairs rotate AB, AC, AD, BC, BD, CD repeated**, so that **any prefix of six calls covers every pair once**. 

- For 4 speakers (A, B, C, D), this balanced rotation ensures pair coverage is preserved even if recording is interrupted.
- The rotation order must be followed as specified in the assignment. Do not reorder pairs arbitrarily.
- This prefix-balanced design means a dropout leaves a balanced design rather than a collapsed pair (see §9).

## 7. Consent checklist and signable paragraph

**Consent checklist (must be completed for every speaker before recording):**

- [ ] **Recording:** I consent to being recorded for this research project.
- [ ] **Evaluation use:** I consent to my recorded speech being used for ASR evaluation in this controlled experiment.
- [ ] **Public demo publication:** I consent to short clips from my recordings being used in a public demo (cut from pilot data as specified).
- [ ] **Storage:** I understand recordings will be stored as specified (audio/gitignored per project structure) and retained per project policy.
- [ ] **Withdrawal before Nov 9 16:00 freeze:** I understand I may withdraw consent before the Nov 9 16:00 freeze. If I withdraw, my recordings will be removed from the corpus to the extent feasible and will not be used in the final analysis.
- [ ] **No PII in metadata:** I understand no personally identifiable information (PII) beyond speaker IDs assigned for the experiment will be stored in metadata/filenames.

**Signable paragraph (read and signed by each speaker):**

> I have read and understood the above consent checklist. I voluntarily consent to participate in the LexiForge recording study under the conditions described. I understand my rights regarding evaluation use, public demo publication, storage, and withdrawal before Nov 9 16:00 freeze, and that no PII will be included in metadata.

**Signature:** ___________  
**Printed name:** ___________  
**Speaker ID (assigned):** ___________  
**Date:** ___________

## 8. QC

**Six QC items (check for every kept file/call):**

1. [ ] **Channel/single device:** Confirmed single device, single room, both speakers present.
2. [ ] **Structure:** AGT/CUS/AGT/CUS/AGT order correct for the call.
3. [ ] **Target terms:** All scripted target terms are present/read as scripted (no unlogged substitutions).
4. [ ] **Intelligibility:** No target term is unintelligible; if any was borderline, retake policy followed and logged.
5. [ ] **Naming/sidecar:** File naming matches `c##_t##_s##_k##`, sidecar JSON complete with required fields.
6. [ ] **Silence/noise:** No long dead air swallowing a target term, no clipping that obscures a target term, no extraneous speech from non-participants.

**Most likely to be skipped:** **#4 (Intelligibility)** — it is easy to assume a term was "close enough" in the moment, especially under time pressure. Intelligibility must be verified against the actual audio for target terms, not assumed.

## 9. Speaker dropout rule

- **Replacement:** If a speaker drops out, they may be replaced **only if the replacement passes the pronunciation guide that day**. The replacement must complete consent (§7) before recording.
- **Fallback:** If a suitable replacement cannot pass the guide that day, **drop to three speakers and 18 calls**. This is the designed fallback.
- **Documentation:** Any dropout, replacement attempt, and the final decision (replacement or drop to 3 speakers/18 calls) must be **fully documented** in the recording log/arbitration log, including timestamps, who decided, and justification. The design's prefix-balanced rotation ensures that dropping to three speakers still leaves a balanced design rather than a collapsed pair.
