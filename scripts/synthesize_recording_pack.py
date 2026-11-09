"""Synthesize the recording pack's calls with Gnani Timbre TTS.

This is the synthetic fallback when human recordings are unavailable. Each turn
is synthesized with a role-specific voice, joined with a short gap, then passed
through the telephony chain (8 kHz, light noise, G.711 mu-law).

The output is internal harness validation, never customer evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lexiforge.audio.telephony import process_telephony, read_wav, write_wav  # noqa: E402
from lexiforge.tts.client import TimbreClient  # noqa: E402
from lexiforge.tts.errors import TTSRateLimitError  # noqa: E402

DEFAULT_CALLS = ("c00", "c01", "c02", "c03")
DEFAULT_AGENT = ("Deepak", "hi-IN")
DEFAULT_CUSTOMER = ("Poorvi", "hi-en")


def _synthesize_with_retry(
    client: Any,
    text: str,
    *,
    voice: str,
    language: str,
    sample_rate: int,
    attempts: int = 6,
    base: float = 5.0,
) -> Any:
    for attempt in range(attempts):
        try:
            return client.synthesize(
                text, voice=voice, language=language, sample_rate=sample_rate
            )
        except TTSRateLimitError:
            if attempt >= attempts - 1:
                raise
            time.sleep(base * (2**attempt))
    raise RuntimeError("unreachable")


def _voice_for(turn: Mapping[str, Any], agent: tuple[str, str], customer: tuple[str, str]) -> tuple[str, str]:
    speaker = str(turn.get("speaker", "")).upper()
    return agent if speaker == "AGT" else customer


def synthesize_call(
    call_id: str,
    script: Mapping[str, Any],
    *,
    client: Any,
    out_path: Path,
    gap_s: float = 0.3,
    noise_snr_db: float = 30.0,
    seed: int = 0,
    agent: tuple[str, str] = DEFAULT_AGENT,
    customer: tuple[str, str] = DEFAULT_CUSTOMER,
) -> dict[str, Any]:
    """Synthesize, join and telephony-process one call."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    turns_dir = out_path.parent / ".turns"
    turns_dir.mkdir(parents=True, exist_ok=True)

    parts: list[np.ndarray] = []
    voices: list[str] = []
    for turn in script.get("turns", []):
        text = str(turn.get("text", "")).strip()
        if not text:
            continue
        voice, language = _voice_for(turn, agent, customer)
        result = _synthesize_with_retry(
            client, text, voice=voice, language=language, sample_rate=8000
        )
        turn_path = turns_dir / f"{call_id}_t{int(turn.get('idx', len(parts) + 1)):02d}.wav"
        turn_path.write_bytes(result.audio)
        samples, sample_rate = read_wav(turn_path)
        parts.append(samples)
        if gap_s > 0:
            parts.append(np.zeros(int(gap_s * sample_rate), dtype=np.float32))
        voices.append(voice)

    if not parts:
        raise ValueError(f"{call_id}: no turns to synthesize")

    audio = np.concatenate(parts)
    processed = process_telephony(
        audio, 8000, noise_snr_db=noise_snr_db, seed=seed
    )
    write_wav(out_path, processed.samples, processed.sample_rate)
    return {
        "call_id": call_id,
        "path": str(out_path),
        "seconds": round(len(processed.samples) / processed.sample_rate, 2),
        "voices": voices,
        "chain": list(processed.chain),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthesize the recording pack with Timbre TTS")
    parser.add_argument("--calls", default=",".join(DEFAULT_CALLS))
    parser.add_argument("--scripts-dir", default="data/scripts")
    parser.add_argument("--out", default="recording/audio")
    parser.add_argument("--agent-voice", default=DEFAULT_AGENT[0])
    parser.add_argument("--agent-language", default=DEFAULT_AGENT[1])
    parser.add_argument("--customer-voice", default=DEFAULT_CUSTOMER[0])
    parser.add_argument("--customer-language", default=DEFAULT_CUSTOMER[1])
    parser.add_argument("--gap", type=float, default=0.3)
    parser.add_argument("--noise-snr-db", type=float, default=30.0)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    from lexiforge.cli import _load_dotenv

    _load_dotenv()
    client = TimbreClient()
    out_dir = Path(args.out)
    calls = [c.strip() for c in args.calls.split(",") if c.strip()]
    for call_id in calls:
        script = json.loads(
            (Path(args.scripts_dir) / f"{call_id}.json").read_text(encoding="utf-8")
        )
        summary = synthesize_call(
            call_id,
            script,
            client=client,
            out_path=out_dir / f"{call_id}.wav",
            gap_s=args.gap,
            noise_snr_db=args.noise_snr_db,
            seed=args.seed,
            agent=(args.agent_voice, args.agent_language),
            customer=(args.customer_voice, args.customer_language),
        )
        print(
            f"{call_id}: {summary['seconds']}s, voices={','.join(sorted(set(summary['voices'])))} "
            f"-> {summary['path']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
