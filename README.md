# LexiForge

A vocabulary-budget risk harness for Gnani Prisma v3.0 on Hinglish banking speech.

**Question:** you get 200 keyterm slots per call and your glossary has 2,000. Which 200 — and what does it cost you when you choose wrong?

**Claim under test:** a mismatched vocabulary measurably corrupts transcripts compared with a matched one, and a cheap per-call selector recovers most of the matched-vocabulary benefit without that corruption.

The selector-vs-static comparison is declared inconclusive in advance: at ~70–75 effective term occurrences the minimum detectable effect is ~20 points. Only large effects are tested here.

- Design: [`docs/design.md`](docs/design.md)
- Notes: [`docs/notes/`](docs/notes/)

Stack: Python 3.11, SQLite, FastAPI, React. Built for the Gnani.ai hackathon, deadline 2026-11-10.
