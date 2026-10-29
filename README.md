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
- Notes: [`docs/notes/`](docs/notes/)

Stack: Python 3.11, SQLite, FastAPI, React.
