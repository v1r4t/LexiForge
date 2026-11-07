"""Telephony audio processing pipeline."""

import wave
from dataclasses import dataclass
from typing import Tuple

import numpy as np
from scipy import signal

# ITU-T G.711 mu-law constants, matching Sun's reference g711.c (and the
# removed ``audioop.lin2ulaw``/``ulaw2lin`` implementation).
_BIAS = 0x84
_CLIP = 32635
_EXP_LUT = tuple(i.bit_length() - 1 if i else 0 for i in range(256))


@dataclass(frozen=True)
class TelephonyAudio:
    samples: np.ndarray
    sample_rate: int
    chain: tuple[str, ...]


def resample_to_8k(samples, sample_rate):
    """Resample audio to 8 kHz using scipy.signal.resample_poly."""
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim > 1:
        samples = samples.flatten()
    if sample_rate == 8000:
        return samples.astype(np.float32)
    # Use resample_poly for rational resampling
    gcd = np.gcd(sample_rate, 8000)
    up = 8000 // gcd
    down = sample_rate // gcd
    resampled = signal.resample_poly(samples, up, down)
    return resampled.astype(np.float32)


def mu_law_encode(samples) -> bytes:
    """Encode float samples in [-1, 1] to ITU-T G.711 mu-law bytes.

    Samples are converted to 16-bit linear PCM (``round(sample * 32768)``,
    saturated to [-32768, 32767]) and then encoded with the standard
    sign/exponent/mantissa algorithm used by Sun's ``g711.c`` and the removed
    ``audioop.lin2ulaw``, so the output interoperates with real mu-law
    decoders.
    """
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim > 1:
        samples = samples.flatten()
    pcm = np.rint(np.clip(samples, -1.0, 1.0) * 32768.0)
    pcm = np.clip(pcm, -32768, 32767).astype(np.int32)

    sign = np.where(pcm < 0, 0x80, 0)
    magnitude = np.minimum(np.where(pcm < 0, -pcm, pcm), _CLIP)
    biased = magnitude + _BIAS
    exponent = np.array(_EXP_LUT, dtype=np.int32)[(biased >> 7) & 0xFF]
    mantissa = (biased >> (exponent + 3)) & 0x0F
    ulaw = (~(sign | (exponent << 4) | mantissa)) & 0xFF
    return ulaw.astype(np.uint8).tobytes()


def mu_law_decode(payload: bytes) -> np.ndarray:
    """Decode ITU-T G.711 mu-law bytes to float samples in [-1, 1]."""
    ulaw = np.frombuffer(payload, dtype=np.uint8).astype(np.int32)
    inverted = (~ulaw) & 0xFF
    sign = inverted & 0x80
    exponent = (inverted >> 4) & 0x07
    mantissa = inverted & 0x0F
    magnitude = (((mantissa << 3) + _BIAS) << exponent) - _BIAS
    pcm = np.where(sign != 0, -magnitude, magnitude)
    return (pcm.astype(np.float32) / 32768.0).astype(np.float32)


def add_noise(samples, *, snr_db: float = 30.0, seed: int = 0) -> np.ndarray:
    """Add additive white Gaussian noise at specified SNR."""
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim > 1:
        samples = samples.flatten()
    rng = np.random.RandomState(seed)
    signal_power = np.mean(samples ** 2)
    if signal_power == 0:
        noise_power = 1e-10
    else:
        noise_power = signal_power / (10 ** (snr_db / 10.0))
    noise = rng.normal(0.0, np.sqrt(noise_power), size=samples.shape)
    noisy = samples + noise.astype(np.float32)
    return noisy.astype(np.float32)


def read_wav(path) -> Tuple[np.ndarray, int]:
    """Read WAV file and return (samples, sample_rate)."""
    with wave.open(str(path), "rb") as wf:
        sample_rate = wf.getframerate()
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        n_frames = wf.getnframes()
        frames = wf.readframes(n_frames)
    if sampwidth == 2:  # 16-bit
        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 1:  # 8-bit
        samples = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128) / 128.0
    elif sampwidth == 4:  # 32-bit
        samples = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if n_channels > 1:
        samples = samples.reshape(-1, n_channels).mean(axis=1)
    return samples.astype(np.float32), sample_rate


def write_wav(path, samples, sample_rate) -> None:
    """Write WAV file."""
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim > 1:
        samples = samples.flatten()
    # Clip and convert to int16
    samples_clipped = np.clip(samples, -1.0, 1.0)
    samples_int16 = (samples_clipped * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(samples_int16.tobytes())


def process_telephony(samples, sample_rate, *, noise_snr_db=30.0, seed=0) -> TelephonyAudio:
    """Process audio through the documented telephony chain.

    Order: resample to 8 kHz -> add white noise -> G.711 mu-law encode/decode.
    """
    chain = []
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim > 1:
        samples = samples.flatten()
    chain.append("input")

    # Resample to 8k
    samples = resample_to_8k(samples, sample_rate)
    chain.append("resample_to_8k")

    # Add noise
    samples = add_noise(samples, snr_db=noise_snr_db, seed=seed)
    chain.append("add_noise")

    # Encode/decode with mu-law (common in telephony)
    encoded = mu_law_encode(samples)
    samples = mu_law_decode(encoded)
    chain.append("mu_law_encode_decode")

    return TelephonyAudio(samples=samples.astype(np.float32), sample_rate=8000, chain=tuple(chain))
