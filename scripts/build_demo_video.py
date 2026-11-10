"""Build the LexiForge demo video from HTML slides + Gnani TTS + ffmpeg.

Output: runs/demo-video/lexiforge-demo.mp4 (1920x1080, ~2:30).

Usage:
  python scripts/build_demo_video.py
  python scripts/build_demo_video.py --voice Kaveri --language en-IN
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
OUT = ROOT / "runs" / "demo-video"

COMMON_CSS = """
*{box-sizing:border-box}
html,body{margin:0;width:1920px;height:1080px;overflow:hidden}
body{
  background:radial-gradient(1200px 700px at 80% -10%,#1b2a52 0%,#0b1020 55%);
  color:#eef2ff;font-family:"Segoe UI",system-ui,-apple-system,sans-serif;
}
.wrap{width:1920px;height:1080px;padding:72px 96px;display:flex;flex-direction:column;justify-content:center}
.kicker{color:#5eead4;font-weight:700;letter-spacing:.18em;text-transform:uppercase;font-size:17px}
h1{font-size:78px;line-height:1.05;margin:18px 0 18px;letter-spacing:-2.2px}
h2{font-size:44px;line-height:1.1;margin:0 0 26px;letter-spacing:-1px}
.sub{color:#9aa6c4;font-size:27px;line-height:1.45;max-width:1500px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:28px;margin-top:34px}
.card{background:#141a2e;border:1px solid #26304d;border-radius:20px;padding:28px 30px}
.card h3{margin:0 0 12px;font-size:19px;color:#5eead4;letter-spacing:.06em;text-transform:uppercase}
.card p{margin:0;color:#9aa6c4;font-size:22px;line-height:1.5}
.flow{display:flex;gap:14px;align-items:center;margin-top:36px;color:#9aa6c4;font-size:22px;flex-wrap:wrap}
.chip{background:#1b2440;border:1px solid #26304d;padding:12px 18px;border-radius:999px}
.arrow{color:#5eead4;font-size:28px}
table{width:100%;border-collapse:collapse;background:#141a2e;border-radius:16px;overflow:hidden;font-size:25px;margin-top:8px}
th,td{padding:15px 18px;text-align:left;border-bottom:1px solid #26304d}
th{color:#9aa6c4;font-size:16px;letter-spacing:.1em;text-transform:uppercase}
tr.hi td{background:#172442}
tr.hi td:first-child{box-shadow:inset 4px 0 0 #5eead4}
.good{color:#5eead4;font-weight:700}.bad{color:#fb7185;font-weight:700}
.callout{margin-top:26px;border-left:5px solid #fbbf24;background:#1c1a10;padding:22px 26px;border-radius:0 16px 16px 0;font-size:24px;color:#e9dfc2}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-top:30px}
.stat{background:#141a2e;border:1px solid #26304d;border-radius:16px;padding:24px}
.stat .v{font-size:42px;font-weight:800;letter-spacing:-1px}
.stat .l{color:#9aa6c4;font-size:19px;margin-top:8px;line-height:1.35}
ul{color:#9aa6c4;margin:10px 0 0 24px;padding:0;font-size:25px;line-height:1.55}
li{margin:12px 0}
.footer{margin-top:34px;color:#9aa6c4;font-size:18px;display:flex;justify-content:space-between;border-top:1px solid #26304d;padding-top:18px}
.tag{background:#2a1e12;color:#fbbf24;border:1px solid #5a3a16;padding:6px 12px;border-radius:999px;font-size:14px;font-weight:700;letter-spacing:.08em}
"""

SLIDES: list[dict[str, Any]] = [
    {
        "name": "01-title",
        "narration": (
            "Gnani gives you two hundred keyterm slots per call. Your glossary is larger. "
            "A wrong list silently costs recognition. LexiForge measures the trade-off on your own audio."
        ),
        "body": """
        <div class="kicker">LexiForge · Gnani Prisma v3.0 · Hinglish banking</div>
        <h1>What does a keyterm list<br>do to this call?</h1>
        <div class="sub">A keyterm-risk harness and measurement service for Hinglish banking calls.</div>
        <div class="flow"><span class="chip">glossary</span><span class="arrow">→</span><span class="chip">select</span><span class="arrow">→</span><span class="chip">six arms</span><span class="arrow">→</span><span class="chip">Keyterm Health Report</span></div>
        """,
    },
    {
        "name": "02-problem",
        "narration": (
            "Vendor benchmarks show relevant keyterms help on public clips. They do not tell a customer "
            "whether a list helps on their own noisy, code-mixed calls, or whether it quietly degrades ordinary recognition. "
            "A wrong list can silently cost brand names or displace words the model already knew."
        ),
        "body": """
        <div class="kicker">The gap</div>
        <h2>Relevant keyterms help.<br>Wrong ones are unmeasured.</h2>
        <div class="grid">
          <div class="card"><h3>Vendor benchmarks</h3><p>Public clips, not the customer's noisy 8 kHz calls, accents, and code-mixing.</p></div>
          <div class="card"><h3>Silent trade-off</h3><p>Brand terms may improve, but ordinary terms can be displaced. The customer-specific trade-off is the missing measurement.</p></div>
        </div>
        <div class="callout">A wrong list is a silent failure: search, analytics, and compliance all inherit it.</div>
        """,
    },
    {
        "name": "03-service",
        "narration": (
            "It takes a glossary, call audio, and reference transcripts, selects a candidate list, "
            "runs controlled arms on the same audio, and returns a Keyterm Health Report."
        ),
        "body": """
        <div class="kicker">What the service does</div>
        <h2>Input → controlled measurement → report</h2>
        <div class="grid">
          <div class="card"><h3>Input</h3><p>Customer glossary, call audio, reference transcripts, and must-have terms.</p></div>
          <div class="card"><h3>Output</h3><p>Term-level recall, insertions, WER, paired deltas, an A/B verdict, and provenance.</p></div>
        </div>
        <div class="callout">A = critical terms: brand, product, scheme. B = all-real guardrail: do not wreck ordinary recognition.</div>
        """,
    },
    {
        "name": "03-arms",
        "narration": (
            "Six arms run on the same audio: baseline, selected, mismatched, hard-negative, oracle, and a static list. "
            "The oracle is the positive control. If a relevant list cannot beat a mismatched one, the pipeline is broken."
        ),
        "body": """
        <div class="kicker">The experiment</div>
        <h2>Six arms, one audio file</h2>
        <table>
          <thead><tr><th>Arm</th><th>Purpose</th></tr></thead>
          <tbody>
            <tr><td>baseline</td><td>No keyterms</td></tr>
            <tr><td>selected (candidate list; brand-only in pilot)</td><td>Selector output; the intervention</td></tr>
            <tr><td>mismatched-200</td><td>Off-domain negative control</td></tr>
            <tr><td>hard-negative-200</td><td>Phonetically close negative control</td></tr>
            <tr class="hi"><td><b>oracle-200</b></td><td><b>Positive control: expected terms + padding</b></td></tr>
            <tr><td>static-head-200</td><td>One fixed core-200 list</td></tr>
          </tbody>
        </table>
        """,
    },
    {
        "name": "04-result",
        "narration": (
            "On four synthetic Hinglish calls, baseline already knew the ordinary terms: ninety-one percent real recall. "
            "Every keyterm list lowered that, even the oracle, down to eighty-two point six. "
            "But fictional-name recall moved as intended: sixteen point seven at baseline, eighty-three for the selected list, "
            "and one hundred for the oracle. The selected list was only eight to nine brand terms, not two hundred."
        ),
        "body": """
        <div class="kicker">Synthetic pilot · 4 calls · transliterated output</div>
        <table>
          <thead><tr><th>Arm</th><th>Real recall</th><th>Fictional-name recall</th><th>Insertions / utt</th></tr></thead>
          <tbody>
            <tr><td>baseline</td><td>21/23 (91.3%)</td><td>2/12 (16.7%)</td><td>0.00</td></tr>
            <tr><td>selected (brand-only, 8–9)</td><td class="bad">16/23 (69.6%)</td><td class="good">10/12 (83.3%)</td><td>0.05</td></tr>
            <tr><td>mismatched-200</td><td>17/23 (73.9%)</td><td>3/12 (25.0%)</td><td>0.10</td></tr>
            <tr><td>hard-negative-200</td><td>18/23 (78.3%)</td><td>2/12 (16.7%)</td><td>0.20</td></tr>
            <tr class="hi"><td><b>oracle-200</b></td><td>19/23 (82.6%)</td><td class="good">12/12 (100%)</td><td>0.10</td></tr>
            <tr><td>static-head-200</td><td>17/23 (73.9%)</td><td>6/12 (50.0%)</td><td>0.00</td></tr>
          </tbody>
        </table>
        <div class="callout">Every list lowered real recall versus baseline — including the oracle. Fictional-name recall moved as intended. Selected was 8–9 brand terms, not 200.</div>
        """,
    },
    {
        "name": "05-stats",
        "narration": (
            "H1 is in the right direction, minus seventeen point five points, but not rejected at p zero point zero six two. "
            "H2 is plus zero point one zero insertions, not rejected. "
            "At four calls the smallest possible p-value is zero point zero six two five. This is descriptive, not confirmatory. "
            "The positive control is directionally consistent, but its confidence interval touches zero. "
            "The selected-versus-baseline B verdict is fail: minus twenty-two point five points, interval minus thirty-six point seven to minus eight point three."
        ),
        "body": """
        <div class="kicker">Pre-registered analysis</div>
        <h2>Direction is right; n=4 cannot reject</h2>
        <div class="stats">
          <div class="stat"><div class="v">−17.5pp</div><div class="l">H1 real recall, p = 0.062<br>not rejected</div></div>
          <div class="stat"><div class="v">+0.10</div><div class="l">H2 insertions/utt, p = 0.503<br>not rejected</div></div>
          <div class="stat"><div class="v">+9.17pp</div><div class="l">oracle − mismatched<br>direction consistent; CI touches zero</div></div>
        </div>
        <div class="callout">Pilot B verdict: selected vs baseline real recall −22.5pp, CI [−36.7, −8.3] — <b>FAIL</b> under the −5pp margin. n=4 cannot reject; smallest one-sided p = 0.0625.</div>
        """,
    },
    {
        "name": "06-why",
        "narration": (
            "Gnani sells the slots. LexiForge measures what a list does on the customer's own calls. "
            "It is a POC accelerator and a glossary guardrail, not a competing ASR. "
            "Deployment alongside the customer's stack is a roadmap item; the pilot ran locally."
        ),
        "body": """
        <div class="kicker">Why it matters to Gnani</div>
        <h2>A measured capability, not another dashboard</h2>
        <ul>
          <li>Gnani sells the 200 slots; LexiForge measures what a list does.</li>
          <li>Customer-specific evidence on their own noisy, code-mixed calls.</li>
          <li>Glossary guardrail: collisions, hard negatives, phonetic confusions.</li>
          <li>Deployment alongside the customer's stack is a roadmap item; the pilot ran locally.</li>
        </ul>
        """,
    },
    {
        "name": "08-architecture",
        "narration": (
            "Under the hood, a Python harness runs the frozen matcher and the six arms. "
            "The matcher has a forty-seven case hand-labelled gold set with a zero point nine eight gate — "
            "stronger evidence than the test count alone. "
            "Gnani REST and Batch clients, plus Timbre TTS, make the study reproducible. "
            "Every arm persists its transcript, so the report can be re-scored offline."
        ),
        "body": """
        <div class="kicker">Built end to end</div>
        <h2>Harness · clients · report</h2>
        <div class="grid">
          <div class="card"><h3>Python harness</h3><p>Frozen matcher, 47-case gold set (≥0.98), six arms, 841 tests.</p></div>
          <div class="card"><h3>Gnani integration</h3><p>REST and Batch clients, Timbre TTS, wire-config validators.</p></div>
          <div class="card"><h3>Artifacts</h3><p>Per-arm transcripts, per-call rows, Keyterm Health Report, provenance.</p></div>
          <div class="card"><h3>Reproducible</h3><p>Offline re-score, hash-stamped inputs, claims register.</p></div>
        </div>
        """,
    },
    {
        "name": "09-limits",
        "narration": (
            "The pilot is synthetic TTS with four calls. The selected arm was eight to nine brand terms, not two hundred. "
            "Output was transliterated: Gnani has not measured transliterated accuracy, and the matcher has no transliteration, "
            "so romanised aliases are a likely confound. At n equals four the smallest p is 0.0625. "
            "Batch stalled; REST chunking over thirty seconds can cut words and context. "
            "Next is twenty calls and real Hinglish audio, then a per-term diff."
        ),
        "body": """
        <div class="kicker">Honest limits</div>
        <h2>Synthetic today. Real audio next.</h2>
        <ul>
          <li>Synthetic TTS, 4 calls, 2 voices — internal harness validation.</li>
          <li>Selected arm was 8–9 brand-only terms, not a 200-term list.</li>
          <li><code>format=transliterate</code>: Gnani accuracy unmeasured; matcher has no transliteration; romanised aliases are a likely confound.</li>
          <li>n=4 cannot reject: minimum one-sided p = 0.0625.</li>
          <li>Batch stalled; REST chunking over 30s can cut words and context.</li>
          <li>Pilot audio was TTS; telephony processing exists but was not verified as applied.</li>
          <li>Report-only; real Hinglish audio is the next milestone.</li>
        </ul>
        """,
    },
    {
        "name": "10-open",
        "narration": (
            "The next step is a per-term diff: for every lost real term, was it absent, substituted, "
            "or present under a different spelling? That separates ASR bias from romanisation drift. "
            "Until then, this is a measured trade-off, not a confirmed harm."
        ),
        "body": """
        <div class="kicker">Open question</div>
        <h2>ASR bias or romanisation drift?</h2>
        <div class="grid">
          <div class="card"><h3>Option A</h3><p>The model is biased by any keyterm list; fictional-name recall is bought at a real-term cost.</p></div>
          <div class="card"><h3>Option B</h3><p>Terms were heard but spelled differently; the matcher misses romanised variants.</p></div>
        </div>
        <div class="callout">The persisted transcripts and the per-term diff decide. Do not claim harm until they do.</div>
        """,
    },
    {
        "name": "11-close",
        "narration": (
            "The repo, report, and design are linked. LexiForge measures what any list does; "
            "it does not promise the right two hundred. Thanks for watching."
        ),
        "body": """
        <div class="kicker">Status and next step</div>
        <h2>Report-only, honest, reproducible</h2>
        <div class="grid">
          <div class="card"><h3>Now</h3><p>841 tests. Six arms. Persisted transcripts. Report and pre-registered analysis.</p></div>
          <div class="card"><h3>Next</h3><p>20 calls. Real Hinglish audio. Per-term diff. Then a confirmatory claim.</p></div>
        </div>
        <div class="footer"><span>github.com/v1r4t/LexiForge</span><span class="tag">INTERNAL HARNESS VALIDATION · SYNTHETIC TTS</span></div>
        """,
    },
]


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return float(out)


def _tts(text: str, out_path: Path, *, voice: str, language: str) -> None:
    from lexiforge.cli import _load_dotenv

    _load_dotenv()
    from lexiforge.tts.client import TimbreClient
    from lexiforge.tts.errors import TTSRateLimitError

    client = TimbreClient()
    for attempt in range(6):
        try:
            result = client.synthesize(
                text, voice=voice, language=language, sample_rate=24000
            )
            out_path.write_bytes(result.audio)
            return
        except TTSRateLimitError:
            if attempt >= 5:
                raise
            time.sleep(5 * (2**attempt))
    raise RuntimeError("unreachable")


def build(*, voice: str, language: str, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    slides_dir = out / "slides"
    audio_dir = out / "audio"
    scenes_dir = out / "scenes"
    for directory in (slides_dir, audio_dir, scenes_dir):
        directory.mkdir(exist_ok=True)

    concat_lines: list[str] = []
    for index, slide in enumerate(SLIDES, start=1):
        html = f"""<!doctype html><html><head><meta charset="utf-8"><style>{COMMON_CSS}</style></head>
<body><div class="wrap">{slide['body']}</div></body></html>"""
        html_path = slides_dir / f"{slide['name']}.html"
        html_path.write_text(html, encoding="utf-8")

        png_path = slides_dir / f"{slide['name']}.png"
        _run(
            [
                str(CHROME),
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--window-size=1920,1080",
                f"--screenshot={png_path}",
                html_path.resolve().as_uri(),
            ]
        )

        wav_path = audio_dir / f"{slide['name']}.wav"
        _tts(slide["narration"], wav_path, voice=voice, language=language)
        seconds = _duration(wav_path) + 0.6

        scene_path = scenes_dir / f"{index:02d}.mp4"
        _run(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                str(png_path),
                "-i",
                str(wav_path),
                "-t",
                f"{seconds:.3f}",
                "-vf",
                "scale=1920:1080,format=yuv420p",
                "-c:v",
                "libx264",
                "-tune",
                "stillimage",
                "-r",
                "30",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-af",
                "apad=pad_dur=0.4",
                "-shortest",
                str(scene_path),
            ]
        )
        concat_lines.append(f"file '{scene_path.as_posix()}'")

    concat_file = out / "concat.txt"
    concat_file.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
    final = out / "lexiforge-demo.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(final),
        ]
    )
    return final


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the LexiForge demo video")
    parser.add_argument("--voice", default="Kaveri")
    parser.add_argument("--language", default="en-IN")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    final = build(voice=args.voice, language=args.language, out=Path(args.out))
    print(f"video: {final}")
    print(f"duration: {_duration(final):.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
