# Recording QC checklist

For every call:

1. [ ] Single device, single room, both speakers present.
2. [ ] AGT/CUS/AGT/CUS/AGT structure matches the sheet.
3. [ ] Every target term was read as scripted; no unlogged substitutions.
4. [ ] No target term is unintelligible. Retakes follow the max-3 rule.
5. [ ] File naming and sidecar metadata are complete.
6. [ ] No long dead air, clipping, or non-participant speech over a target term.

Also confirm per call: the signed `consent.md` is on file (`consent_ref`), and
`pii_status` is set to `redacted` or has documented approval. Speaker IDs only;
no names, phone numbers, account numbers or e-mail addresses in metadata or
filenames.

## Retake log

| call_id | turn_id | take | reason | decision | recorder | timestamp |
|---|---|---|---|---|---|---|
| | | | | | | |

Rejected takes go to `audio/quarantine/`; never delete them.
