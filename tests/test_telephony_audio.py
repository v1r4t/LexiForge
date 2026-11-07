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
    assert len(result.chain) > 0
    # Chain should record steps in order
    assert "resample" in str(result.chain).lower() or "resample" in result.chain[0].lower()
