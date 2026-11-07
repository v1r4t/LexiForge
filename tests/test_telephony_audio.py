"""Tests for telephony audio pipeline."""

import os
import tempfile

import numpy as np

from lexiforge.audio.telephony import (
    TelephonyAudio,
    add_noise,
    mu_law_decode,
    mu_law_encode,
    process_telephony,
    read_wav,
    resample_to_8k,
    write_wav,
)

# (16-bit PCM input, expected ITU-T G.711 mu-law codeword). These are reference
# values from CPython's audioop.lin2ulaw before the module was removed, not
# self-generated round-trips. They include silence, both saturation rails and
# points on the logarithmic segment table.
MU_LAW_ENCODE_VECTORS = [
    (0, 0xFF),
    (1, 0xFF),
    (4, 0xFE),
    (100, 0xF2),
    (-100, 0x72),
    (1000, 0xCE),
    (-1000, 0x4E),
    (4096, 0xAF),
    (8192, 0x9F),
    (16384, 0x8F),
    (32767, 0x80),
    (-32768, 0x00),
]

# Decoded 16-bit PCM for the same codewords, from audioop.ulaw2lin.
MU_LAW_DECODE_VECTORS = [
    (0xFF, 0),
    (0xFE, 8),
    (0xF2, 104),
    (0x72, -104),
    (0xCE, 988),
    (0x4E, -988),
    (0xAF, 4092),
    (0x9F, 8316),
    (0x8F, 16764),
    (0x80, 32124),
    (0x00, -32124),
]


def test_mu_law_known_vectors_encode():
    pcm = np.array([value for value, _ in MU_LAW_ENCODE_VECTORS], dtype=np.float32)
    encoded = mu_law_encode(pcm / 32768.0)
    expected = bytes(codeword for _, codeword in MU_LAW_ENCODE_VECTORS)
    assert encoded == expected


def test_mu_law_known_vectors_decode():
    payload = bytes(codeword for codeword, _ in MU_LAW_DECODE_VECTORS)
    decoded = mu_law_decode(payload)
    expected = (
        np.array([pcm for _, pcm in MU_LAW_DECODE_VECTORS], dtype=np.float32) / 32768.0
    )
    assert np.allclose(decoded, expected, atol=1e-7)


def test_mu_law_saturates_out_of_range_input():
    encoded = mu_law_encode(np.array([2.0, -2.0], dtype=np.float32))
    assert encoded == bytes([0x80, 0x00])


def test_resample_tone_48k_to_8k():
    sr = 48000
    duration = 0.1
    t = np.arange(int(sr * duration)) / sr
    samples = 0.5 * np.sin(2 * np.pi * 440 * t)
    out = resample_to_8k(samples, sr)
    assert len(out) == int(round(duration * 8000))
    # Check dominant frequency is near 440 Hz
    if len(out) > 0:
        spectrum = np.abs(np.fft.rfft(out))
        freqs = np.fft.rfftfreq(len(out), 1 / 8000)
        peak_idx = np.argmax(spectrum)
        assert abs(freqs[peak_idx] - 440) < 50


def test_resample_tone_16k_to_8k():
    sr = 16000
    duration = 0.1
    t = np.arange(int(sr * duration)) / sr
    samples = 0.5 * np.sin(2 * np.pi * 440 * t)
    out = resample_to_8k(samples, sr)
    assert len(out) == int(round(duration * 8000))


def test_resample_tone_8k_to_8k():
    sr = 8000
    duration = 0.1
    t = np.arange(int(sr * duration)) / sr
    samples = 0.5 * np.sin(2 * np.pi * 440 * t)
    out = resample_to_8k(samples, sr)
    assert len(out) == int(round(duration * 8000))


def test_mu_law_roundtrip_snr():
    sr = 8000
    duration = 0.5
    t = np.arange(int(sr * duration)) / sr
    samples = 0.5 * np.sin(2 * np.pi * 440 * t)
    encoded = mu_law_encode(samples)
    decoded = mu_law_decode(encoded)
    assert len(encoded) == len(samples)
    # Compute SNR
    noise = decoded - samples[: len(decoded)]
    signal_power = np.mean(samples[: len(decoded)] ** 2)
    noise_power = np.mean(noise ** 2)
    if noise_power > 0:
        snr = 10 * np.log10(signal_power / noise_power)
        assert snr >= 30
    else:
        assert False


def test_byte_length_equals_sample_count():
    samples = np.array([0.1, -0.2, 0.3, -0.4], dtype=np.float32)
    encoded = mu_law_encode(samples)
    assert len(encoded) == len(samples)


def test_noise_deterministic_by_seed():
    samples = np.ones(1000) * 0.1
    noise1 = add_noise(samples, snr_db=30.0, seed=123)
    noise2 = add_noise(samples, snr_db=30.0, seed=123)
    noise3 = add_noise(samples, snr_db=30.0, seed=456)
    assert np.allclose(noise1, noise2)
    assert not np.allclose(noise1, noise3)


def test_wav_roundtrip():
    samples = 0.3 * np.sin(2 * np.pi * 440 * np.arange(8000) / 8000)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    try:
        write_wav(path, samples, 8000)
        loaded, sr = read_wav(path)
        assert sr == 8000
        assert np.allclose(loaded, samples, atol=1e-4)
    finally:
        os.unlink(path)


def test_process_telephony_chain():
    sr = 16000
    duration = 0.1
    t = np.arange(int(sr * duration)) / sr
    samples = 0.5 * np.sin(2 * np.pi * 440 * t)
    result = process_telephony(samples, sr, noise_snr_db=30.0, seed=0)
    assert isinstance(result, TelephonyAudio)
    assert result.sample_rate == 8000
    assert isinstance(result.chain, tuple)
    assert result.chain == ("input", "resample_to_8k", "add_noise", "mu_law_encode_decode")
