# LexiForge — 2:30 demo video script

**Goal:** show the problem, the measurement service, and the pilot result in
2–3 minutes. Record the screen, not a live transcription run.

## Before recording (5 minutes)

1. Open `docs/demo.html` in Chrome, full screen, 1080p.
2. Open a terminal at the repo root with a large font (`Ctrl + +`).
3. For the terminal segment, run this once *before* recording and leave the
   output on screen:
   ```bash
   python -m lexiforge.cli info
   ```
4. Optional second terminal output, pre-run:
   ```bash
   python scripts/run_keyterm_study.py recording/manifest.pilot4.json --glossary data/glossary.json
   ```
   It prints `Dry run ... 4 call plans`. Do not run the live transcription.
5. Close Slack/Discord/email. Do **not** show `.env` or the API key.
6. Test the microphone for 10 seconds.

## Storyboard

### 0:00–0:20 — hook
**Show:** `docs/demo.html` title.
**Say:**
> Gnani gives you 200 keyterm slots per call. Your glossary is larger. A wrong
> list silently costs recognition. LexiForge measures the trade-off on your own
> audio.

### 0:20–0:40 — the service
**Show:** the input → select → six arms → report flow on the page.
**Say:**
> It takes a glossary, call audio, and reference transcripts, selects a
> candidate list, runs controlled arms on the same audio, and returns a Keyterm
> Health Report.

### 0:40–1:00 — the arms
**Show:** the flow chips / table header.
**Say:**
> Baseline, selected, mismatched, hard-negative, oracle, and a static list.
> The oracle is the positive control: if a relevant list cannot beat a
> mismatched one, the pipeline is broken.

### 1:00–1:35 — result
**Show:** the six-arm table.
**Say:**
> On four synthetic Hinglish calls, baseline already knew the ordinary terms:
> 91 percent real recall. Every keyterm list lowered that — even the oracle,
> down to 82.6. But brand recall moved exactly as intended: 16.7 at baseline,
> 83.3 for the selected list, 100 for the oracle.

### 1:35–1:55 — the statistics
**Show:** the three stat cards.
**Say:**
> H1 is in the right direction, minus 17.5 points, but not rejected at p 0.062.
> H2 is plus 0.10 insertions, not rejected. At four calls the smallest possible
> p-value is 0.0625, so this is descriptive, not confirmatory. The positive
> control passes.

### 1:55–2:15 — why it matters
**Show:** “Why this matters to Gnani” list.
**Say:**
> Gnani sells the slots. LexiForge makes sure the 200 are the right 200, and
> proves it on the customer's calls. It runs in-VPC, so regulated BFSI data does
> not leave the environment.

### 2:15–2:30 — limits and close
**Show:** footer + repo URL.
**Say:**
> The pilot is synthetic and internal-only. Next is 20 calls and real Hinglish
> audio. The repo, report, and design are linked. Thanks.

## Upload

1. Stop recording; trim silence at the start/end in Clipchamp if needed.
2. Upload to **YouTube (Unlisted)** or Google Drive.
3. Set “anyone with the link can view.”
4. Open the link in an incognito window to verify it works.
5. Submit:
   - Project URL: `https://github.com/v1r4t/LexiForge`
   - Pitch: `PITCH.md` in that repo
   - Video: the unlisted link

## If something fails

- If the terminal output is slow, skip it and stay on `docs/demo.html`.
- If you stumble, keep going; one take is fine.
- Do not attempt the live study or a real-audio run during the recording.
