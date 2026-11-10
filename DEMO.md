# LexiForge — 2:30 demo video script

**Goal:** show the problem, the measurement service, and the pilot result
honestly. Record the screen; do not run a live transcription.

## Before recording

1. Open `docs/demo.html` in Chrome, full screen, 1080p.
2. Open a terminal at the repo root with a large font.
3. Optional: run `python -m lexiforge.cli info` once and leave the output up.
4. Close notifications. Do **not** show `.env` or the API key.
5. Test the microphone.

## Storyboard

### 0:00–0:20 — hook
**Show:** demo page title.
**Say:**
> Gnani gives you 200 keyterm slots per call. Your glossary is larger. LexiForge
> measures what a candidate list does on your own audio — and whether it helped
> or hurt.

### 0:20–0:40 — the gap
**Show:** the two problem cards.
**Say:**
> Vendor benchmarks show relevant keyterms help on public clips. They do not
> tell a customer whether a list helps on their noisy, code-mixed calls, or
> whether it degrades ordinary recognition.

### 0:40–1:00 — the service
**Show:** input → select → six arms → report flow.
**Say:**
> It takes a glossary, call audio, and reference transcripts, selects a
> candidate list, runs controlled arms on the same audio, and returns a Keyterm
> Health Report.

### 1:00–1:20 — the arms
**Show:** the six-arm list.
**Say:**
> Baseline, selected, mismatched, hard-negative, oracle, and static. The oracle
> is the positive control: if a relevant list cannot beat a mismatched one, the
> pipeline is broken.

### 1:20–1:50 — result
**Show:** the result table.
**Say:**
> On four synthetic Hinglish calls, baseline already knew the ordinary terms:
> 91 percent real recall. Every keyterm list lowered that, even the oracle, down
> to 82.6. But fictional-name recall moved as intended: 16.7 at baseline, 83.3
> for the selected list, 100 for the oracle. The selected list was only 8 to 9
> brand terms, not 200.

### 1:50–2:10 — statistics
**Show:** the three stat cards and the verdict line.
**Say:**
> H1 is in the right direction, minus 17.5 points, but not rejected at p 0.062.
> H2 is plus 0.10 insertions, not rejected. At four calls the smallest possible
> p is 0.0625, so this is descriptive. The positive control is directionally
> consistent, but its CI touches zero. The selected-versus-baseline B verdict is
> fail: minus 22.5 points, interval minus 36.7 to minus 8.3.

### 2:10–2:25 — why Gnani
**Show:** “Why this matters” list.
**Say:**
> Gnani sells the slots. LexiForge measures what a list does on the customer's
> own calls. It is a POC accelerator and a glossary guardrail, not a competing
> ASR. Deployment alongside the customer's stack is a roadmap item.

### 2:25–2:40 — limits and open question
**Show:** the limits list and the open-question callout.
**Say:**
> The pilot is synthetic, transliterated, and underpowered. Gnani has not
> measured transliterated accuracy, and the matcher has no transliteration, so
> romanised aliases are a likely confound. The per-term diff decides whether
> this is ASR bias or spelling drift. Do not claim harm until it does.

### 2:40–2:50 — close
**Show:** footer and repo URL.
**Say:**
> LexiForge measures what any list does; it does not promise the right 200.
> The repo, report, and design are linked. Thanks.

## Upload

1. Stop recording; trim silence in Clipchamp if needed.
2. Upload to **YouTube (Unlisted)** or Google Drive.
3. Set “anyone with the link can view.”
4. Open the link in incognito to verify.
5. Submit the repo URL and the unlisted video link.

## Notes

- Do not claim the pilot used 200 terms, real customer audio, noisy 8 kHz
  processing, or an in-VPC deployment.
- The matcher gold set is 47 hand-labelled cases with a ≥0.98 gate.
- Batch queue instability is why the study used REST; calls over 30 seconds are
  chunked, which is a confound for the 20-call run.
