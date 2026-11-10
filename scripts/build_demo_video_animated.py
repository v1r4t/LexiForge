"""Build the animated LexiForge demo video (editorial redesign, CSS motion).

Reuses the existing Gnani TTS narration in runs/demo-video/audio/.
Captures frames with puppeteer-core + Chrome, assembles with ffmpeg.

Usage:
  python scripts/build_demo_video_animated.py
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
CAPTURE = ROOT / "scripts" / "capture_frames.js"
AUDIO_DIR = ROOT / "runs" / "demo-video" / "audio"
OUT = ROOT / "runs" / "demo-video-v2"
AUDIO_MAP = {
    "04-arms": "03-arms.wav",
    "05-result": "04-result.wav",
    "06-stats": "05-stats.wav",
    "07-why": "06-why.wav",
}
NODE_PATH = Path(r"C:\Users\itzdh\AppData\Local\Temp\opencode\video-tools\node_modules")
FPS = 20

CSS = """
:root{
  --paper:#f3eee4; --ink:#17140f; --muted:#6d675c; --accent:#c6472a; --line:#cfc6b6;
}
*{box-sizing:border-box}
html,body{margin:0;width:1920px;height:1080px;overflow:hidden;background:var(--paper);color:var(--ink);
  font-family:"Segoe UI",Helvetica,Arial,sans-serif}
.wrap{width:1920px;height:1080px;padding:86px 110px;position:relative;overflow:hidden}
.kicker{font:600 15px/1 Consolas,"Courier New",monospace;letter-spacing:.18em;text-transform:uppercase;color:var(--accent)}
.mono{font-family:Consolas,"Courier New",monospace}
.muted{color:var(--muted)}
h1{font-family:Georgia,"Times New Roman",serif;font-weight:400;font-size:104px;line-height:.98;
  letter-spacing:-3px;margin:26px 0 20px}
h2{font-family:Georgia,"Times New Roman",serif;font-weight:400;font-size:62px;line-height:1.04;
  letter-spacing:-1.8px;margin:20px 0 28px;max-width:1560px}
.sub{font-size:28px;line-height:1.4;color:var(--muted);max-width:1280px;margin-top:22px}
.rule{height:2px;background:var(--ink);transform-origin:left;animation:draw .9s cubic-bezier(.2,.7,.2,1) both}
.reveal{animation:rise .8s cubic-bezier(.2,.7,.2,1) both}
.fade{animation:fade .9s ease both}
@keyframes draw{0%{transform:scaleX(0)}100%{transform:scaleX(1)}}
@keyframes rise{0%{opacity:0;transform:translateY(20px)}100%{opacity:1;transform:none}}
@keyframes fade{0%{opacity:0}100%{opacity:1}}
@keyframes row{0%{opacity:0;transform:translateX(-16px)}100%{opacity:1;transform:none}}
@keyframes grow{0%{width:0}100%{width:var(--w)}}
@keyframes growY{0%{transform:scaleY(0)}100%{transform:scaleY(1)}}
.footer{position:absolute;left:110px;bottom:64px;font-size:14px;letter-spacing:.12em;color:var(--muted)}

/* problem */
.split{display:grid;grid-template-columns:1fr 1fr;gap:90px;margin-top:34px;border-top:2px solid var(--line);padding-top:30px}
.bignum{font-family:Georgia,"Times New Roman",serif;font-size:150px;line-height:.82;letter-spacing:-7px}
.label{font:600 15px/1.3 Consolas,"Courier New",monospace;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin-top:16px}
.pull{font-family:Georgia,"Times New Roman",serif;font-size:35px;line-height:1.25;max-width:1480px;
  margin-top:38px;border-left:4px solid var(--accent);padding-left:26px}

/* service */
.steps{display:grid;grid-template-columns:repeat(4,1fr);gap:34px;margin-top:58px}
.step{border-top:2px solid var(--ink);padding-top:18px;transform-origin:left;animation:draw .8s cubic-bezier(.2,.7,.2,1) both}
.step .n{font:600 14px/1 Consolas,"Courier New",monospace;color:var(--accent);letter-spacing:.18em}
.step h3{font-family:Georgia,"Times New Roman",serif;font-weight:400;font-size:32px;line-height:1.1;margin:14px 0 8px}
.step p{margin:0;color:var(--muted);font-size:19px;line-height:1.35}
.note{margin-top:44px;font:500 18px/1.4 Consolas,"Courier New",monospace;color:var(--muted);letter-spacing:.04em}

/* tables */
table{width:100%;border-collapse:collapse;margin-top:14px}
th{font:600 14px/1 Consolas,"Courier New",monospace;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);text-align:left;padding:12px 16px;border-bottom:2px solid var(--ink)}
td{padding:15px 16px;border-bottom:1px solid var(--line);font-size:26px}
tr.row{animation:row .55s cubic-bezier(.2,.7,.2,1) both}
tr.hi td{border-top:2px solid var(--accent);border-bottom:2px solid var(--accent);background:rgba(198,71,42,.06)}
tr.hi td:first-child{box-shadow:inset 4px 0 0 var(--accent)}
.num{font-variant-numeric:tabular-nums}
.bad{color:var(--accent);font-weight:700}
.good{font-weight:700}

/* stats */
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:70px;margin-top:52px}
.stat .v{font-family:Georgia,"Times New Roman",serif;font-size:82px;line-height:1;letter-spacing:-2px}
.stat .c{font:500 17px/1.35 Consolas,"Courier New",monospace;color:var(--muted);margin-top:12px}
.bar{height:7px;background:var(--line);margin-top:18px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--accent);width:var(--w);animation:grow 1.1s cubic-bezier(.2,.7,.2,1) both}
.stamp{position:absolute;left:110px;bottom:86px;border:3px solid var(--accent);color:var(--accent);
  padding:14px 20px;font:700 20px/1.2 Consolas,"Courier New",monospace;letter-spacing:.08em;transform:rotate(-1.5deg);animation:rise .7s 1.1s both}

/* why */
.two{display:grid;grid-template-columns:1fr 1fr;gap:80px;margin-top:30px;border-top:2px solid var(--line);padding-top:30px}
.two .label{margin-top:0}
.two p{font-family:Georgia,"Times New Roman",serif;font-size:31px;line-height:1.3;margin:14px 0 0;max-width:640px}
.footnote{position:absolute;left:110px;bottom:80px;font-size:18px;color:var(--muted);max-width:1500px;line-height:1.4}

/* architecture */
.diagram{display:flex;align-items:center;gap:22px;margin-top:64px}
.node{border:2px solid var(--ink);padding:24px 26px;font:600 20px/1.3 Consolas,"Courier New",monospace;min-width:300px;text-align:center}
.connector{height:2px;background:var(--ink);flex:1;transform-origin:left;animation:draw .8s cubic-bezier(.2,.7,.2,1) both}
.tags{display:flex;gap:28px;margin-top:46px;font:500 17px/1 Consolas,"Courier New",monospace;color:var(--muted);letter-spacing:.06em}

/* limits */
.ledger{list-style:none;margin:34px 0 0;padding:0}
.ledger li{display:flex;gap:26px;border-top:1px solid var(--line);padding:14px 0;animation:rise .6s both}
.ledger .n{font:600 14px/1.4 Consolas,"Courier New",monospace;color:var(--accent);letter-spacing:.12em;min-width:34px}
.ledger p{margin:0;font-size:23px;line-height:1.35;max-width:1500px}
.ledger p b{color:var(--accent)}

/* fork */
.fork{display:grid;grid-template-columns:1fr 2px 1fr;gap:48px;margin-top:52px;align-items:start}
.vline{background:var(--ink);height:330px;transform-origin:top;animation:growY .9s cubic-bezier(.2,.7,.2,1) both}
.fork .tag{font:700 14px/1 Consolas,"Courier New",monospace;color:var(--accent);letter-spacing:.2em}
.fork h3{font-family:Georgia,"Times New Roman",serif;font-weight:400;font-size:42px;line-height:1.1;margin:16px 0 14px}
.fork p{font-size:22px;line-height:1.45;color:var(--muted);margin:0;max-width:620px}
.verdict{position:absolute;left:110px;bottom:80px;font:500 19px/1.4 Consolas,"Courier New",monospace;color:var(--accent);letter-spacing:.03em}
"""

SLIDES: list[dict[str, Any]] = [
    {
        "name": "01-title",
        "body": """
        <div class="kicker reveal" style="animation-delay:.05s">LexiForge · Keyterm Health · Hinglish banking</div>
        <h1 class="reveal" style="animation-delay:.16s">What does a keyterm list<br>do to a call?</h1>
        <div class="rule" style="animation-delay:.55s"></div>
        <div class="sub reveal" style="animation-delay:.72s">A measurement service for Gnani Prisma v3.0.<br>Same audio. Six arms. One report.</div>
        <div class="footer mono fade" style="animation-delay:1.05s">SYNTHETIC PILOT · 4 CALLS · INTERNAL VALIDATION</div>
        """,
    },
    {
        "name": "02-problem",
        "body": """
        <div class="kicker reveal" style="animation-delay:.05s">The gap</div>
        <h2 class="reveal" style="animation-delay:.15s">Relevant keyterms help.<br>The wrong list is unmeasured.</h2>
        <div class="split">
          <div class="reveal" style="animation-delay:.4s"><div class="bignum">200</div><div class="label">keyterm slots per call</div></div>
          <div class="reveal" style="animation-delay:.55s"><div class="bignum">1,000</div><div class="label">terms in the committed glossary</div></div>
        </div>
        <div class="pull reveal" style="animation-delay:.85s">Vendor benchmarks use public clips. The customer's calls are the missing evidence.</div>
        """,
    },
    {
        "name": "03-service",
        "body": """
        <div class="kicker reveal" style="animation-delay:.05s">The service</div>
        <h2 class="reveal" style="animation-delay:.15s">Input → controlled arms → report</h2>
        <div class="steps">
          <div class="step" style="animation-delay:.35s"><div class="n">01</div><h3>Glossary</h3><p>Customer terms, categories, must-haves.</p></div>
          <div class="step" style="animation-delay:.5s"><div class="n">02</div><h3>Audio + references</h3><p>Hinglish calls and human transcripts.</p></div>
          <div class="step" style="animation-delay:.65s"><div class="n">03</div><h3>Six arms</h3><p>Same audio; only the keyterm list changes.</p></div>
          <div class="step" style="animation-delay:.8s"><div class="n">04</div><h3>Report</h3><p>Recall, insertions, deltas, verdict, provenance.</p></div>
        </div>
        <div class="note fade" style="animation-delay:1.15s">A = critical terms. B = all-real guardrail. Both are always reported.</div>
        """,
    },
    {
        "name": "04-arms",
        "body": """
        <div class="kicker reveal" style="animation-delay:.05s">The experiment</div>
        <h2 class="reveal" style="animation-delay:.15s">Six arms, one audio file</h2>
        <table>
          <thead><tr><th>Arm</th><th>Role</th></tr></thead>
          <tbody>
            <tr class="row" style="animation-delay:.35s"><td>baseline</td><td>No keyterms</td></tr>
            <tr class="row" style="animation-delay:.45s"><td>selected</td><td>Candidate list; brand-only in the pilot</td></tr>
            <tr class="row" style="animation-delay:.55s"><td>mismatched-200</td><td>Off-domain negative control</td></tr>
            <tr class="row" style="animation-delay:.65s"><td>hard-negative-200</td><td>Phonetically close negative control</td></tr>
            <tr class="row hi" style="animation-delay:.75s"><td><b>oracle-200</b></td><td>Expected terms + padding; positive control</td></tr>
            <tr class="row" style="animation-delay:.85s"><td>static-head-200</td><td>One fixed core-200 list</td></tr>
          </tbody>
        </table>
        """,
    },
    {
        "name": "05-result",
        "body": """
        <div class="kicker reveal" style="animation-delay:.05s">Synthetic pilot · 4 calls · transliterated output</div>
        <table>
          <thead><tr><th>Arm</th><th>Real recall</th><th>Fictional-name recall</th><th>Insertions / utt</th></tr></thead>
          <tbody>
            <tr class="row" style="animation-delay:.25s"><td>baseline</td><td class="num">21/23 (91.3%)</td><td class="num">2/12 (16.7%)</td><td class="num">0.00</td></tr>
            <tr class="row hi" style="animation-delay:.35s"><td><b>selected (brand-only, 8–9)</b></td><td class="num bad">16/23 (69.6%)</td><td class="num good">10/12 (83.3%)</td><td class="num">0.05</td></tr>
            <tr class="row" style="animation-delay:.45s"><td>mismatched-200</td><td class="num">17/23 (73.9%)</td><td class="num">3/12 (25.0%)</td><td class="num">0.10</td></tr>
            <tr class="row" style="animation-delay:.55s"><td>hard-negative-200</td><td class="num">18/23 (78.3%)</td><td class="num">2/12 (16.7%)</td><td class="num">0.20</td></tr>
            <tr class="row hi" style="animation-delay:.65s"><td><b>oracle-200</b></td><td class="num">19/23 (82.6%)</td><td class="num good">12/12 (100%)</td><td class="num">0.10</td></tr>
            <tr class="row" style="animation-delay:.75s"><td>static-head-200</td><td class="num">17/23 (73.9%)</td><td class="num">6/12 (50.0%)</td><td class="num">0.00</td></tr>
          </tbody>
        </table>
        <div class="note fade" style="animation-delay:1s">Every list lowered real recall versus baseline — including the oracle. Selected was 8–9 brand terms, not 200.</div>
        """,
    },
    {
        "name": "06-stats",
        "body": """
        <div class="kicker reveal" style="animation-delay:.05s">Pre-registered analysis</div>
        <h2 class="reveal" style="animation-delay:.15s">Direction is right. n=4 cannot reject.</h2>
        <div class="stats">
          <div class="stat reveal" style="animation-delay:.35s"><div class="v">−17.5pp</div><div class="c">H1 real recall · p 0.062 · not rejected</div><div class="bar"><i style="--w:74%"></i></div></div>
          <div class="stat reveal" style="animation-delay:.5s"><div class="v">+0.10</div><div class="c">H2 insertions/utt · p 0.503 · not rejected</div><div class="bar"><i style="--w:28%"></i></div></div>
          <div class="stat reveal" style="animation-delay:.65s"><div class="v">+9.17pp</div><div class="c">oracle − mismatched · direction consistent; CI touches zero</div><div class="bar"><i style="--w:45%"></i></div></div>
        </div>
        <div class="stamp">PILOT B VERDICT · FAIL · −22.5pp [−36.7, −8.3]</div>
        """,
    },
    {
        "name": "07-why",
        "body": """
        <div class="kicker reveal" style="animation-delay:.05s">Why Gnani</div>
        <h2 class="reveal" style="animation-delay:.15s">A measured capability,<br>not another dashboard.</h2>
        <div class="two">
          <div class="reveal" style="animation-delay:.4s"><div class="label">Gnani sells</div><p>200 keyterm slots and the Prisma model.</p></div>
          <div class="reveal" style="animation-delay:.55s"><div class="label">LexiForge adds</div><p>Selection, glossary guardrails, and customer-specific proof.</p></div>
        </div>
        <div class="footnote fade" style="animation-delay:.9s">Deployment alongside the customer's stack is a roadmap item. The pilot ran locally.</div>
        """,
    },
    {
        "name": "08-architecture",
        "body": """
        <div class="kicker reveal" style="animation-delay:.05s">Built end to end</div>
        <h2 class="reveal" style="animation-delay:.15s">Harness → clients → report</h2>
        <div class="diagram">
          <div class="node reveal" style="animation-delay:.35s">Glossary + calls</div>
          <div class="connector" style="animation-delay:.5s"></div>
          <div class="node reveal" style="animation-delay:.6s">Six-arm harness</div>
          <div class="connector" style="animation-delay:.75s"></div>
          <div class="node reveal" style="animation-delay:.85s">Keyterm Health Report</div>
        </div>
        <div class="tags fade" style="animation-delay:1.05s">
          <span>REST / Batch / Timbre TTS</span><span>47-case gold set · ≥0.98</span><span>Persisted transcripts</span>
        </div>
        """,
    },
    {
        "name": "09-limits",
        "body": """
        <div class="kicker reveal" style="animation-delay:.05s">Honest limits</div>
        <h2 class="reveal" style="animation-delay:.15s">Synthetic today. Real audio next.</h2>
        <ul class="ledger">
          <li style="animation-delay:.3s"><span class="n">01</span><p>Synthetic TTS, 4 calls, 2 voices — internal harness validation.</p></li>
          <li style="animation-delay:.38s"><span class="n">02</span><p><b>Selected arm was 8–9 brand-only terms, not a 200-term list.</b></p></li>
          <li style="animation-delay:.46s"><span class="n">03</span><p><b>format=transliterate</b>: Gnani accuracy unmeasured; matcher has no transliteration; romanised aliases are a likely confound.</p></li>
          <li style="animation-delay:.54s"><span class="n">04</span><p>n=4 cannot reject: minimum one-sided p = 0.0625.</p></li>
          <li style="animation-delay:.62s"><span class="n">05</span><p>Batch stalled; REST chunking over 30s can cut words and context.</p></li>
          <li style="animation-delay:.7s"><span class="n">06</span><p>Pilot audio was TTS; telephony processing exists but was not verified as applied.</p></li>
        </ul>
        """,
    },
    {
        "name": "10-open",
        "body": """
        <div class="kicker reveal" style="animation-delay:.05s">Open question</div>
        <h2 class="reveal" style="animation-delay:.15s">ASR bias or romanisation drift?</h2>
        <div class="fork">
          <div class="reveal" style="animation-delay:.4s"><div class="tag">A</div><h3>Model bias</h3><p>Any keyterm list shifts the decoder; fictional-name recall is bought at a real-term cost.</p></div>
          <div class="vline" style="animation-delay:.55s"></div>
          <div class="reveal" style="animation-delay:.7s"><div class="tag">B</div><h3>Romanisation drift</h3><p>Terms were heard but spelled differently; the matcher misses romanised variants.</p></div>
        </div>
        <div class="verdict fade" style="animation-delay:1s">The per-term diff decides. Do not claim harm until it does.</div>
        """,
    },
    {
        "name": "11-close",
        "body": """
        <div class="kicker reveal" style="animation-delay:.05s">LexiForge</div>
        <h1 class="reveal" style="animation-delay:.15s">Measure the list.</h1>
        <div class="rule" style="animation-delay:.5s"></div>
        <div class="sub reveal" style="animation-delay:.68s">It does not promise the right 200.<br>It measures what any list does.</div>
        <div class="footer mono fade" style="animation-delay:1s">github.com/v1r4t/LexiForge · INTERNAL HARNESS VALIDATION</div>
        """,
    },
]


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def _run(cmd: list[str], **kwargs: Any) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True, **kwargs)


def build(*, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    slides_dir = out / "slides"
    frames_root = out / "frames"
    scenes_dir = out / "scenes"
    for directory in (slides_dir, frames_root, scenes_dir):
        directory.mkdir(exist_ok=True)

    concat: list[str] = []
    for index, slide in enumerate(SLIDES, start=1):
        name = slide["name"]
        audio = AUDIO_DIR / AUDIO_MAP.get(name, f"{name}.wav")
        if not audio.exists():
            raise FileNotFoundError(f"missing narration audio: {audio}")
        seconds = _duration(audio) + 0.8

        html = (
            "<!doctype html><html><head><meta charset='utf-8'><style>"
            + CSS
            + "</style></head><body><div class='wrap'>"
            + slide["body"]
            + "</div></body></html>"
        )
        html_path = slides_dir / f"{name}.html"
        html_path.write_text(html, encoding="utf-8")
        frames_dir = frames_root / f"{index:02d}"
        env = dict(os.environ)
        env["NODE_PATH"] = str(NODE_PATH)
        _run(
            ["node", str(CAPTURE), str(CHROME), str(html_path), str(frames_dir), str(FPS), f"{seconds:.3f}"],
            env=env,
        )
        scene = scenes_dir / f"{index:02d}.mp4"
        _run(
            [
                "ffmpeg", "-y", "-framerate", str(FPS), "-i", str(frames_dir / "%04d.jpg"),
                "-i", str(audio), "-af", "apad=pad_dur=0.8", "-t", f"{seconds:.3f}",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-shortest", str(scene),
            ]
        )
        concat.append(f"file '{scene.as_posix()}'")

    concat_file = out / "concat.txt"
    concat_file.write_text("\n".join(concat) + "\n", encoding="utf-8")
    final = out / "lexiforge-demo.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(final)])
    return final


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the animated LexiForge demo video")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    final = build(out=Path(args.out))
    print(f"video: {final}")
    print(f"duration: {_duration(final):.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
