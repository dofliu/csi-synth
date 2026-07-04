"""
estimate.py — Vital-sign estimation from CSI (breathing/heart rate).

This is deliberately a SIMPLE, transparent estimator (bandpass + DFT peak).
Its purpose here is VALIDATION: if we feed the generator's output back in and
recover the breathing rate we set, the physics core is correct.

It is NOT the research model — the thesis model (dual-task BiLSTM + PASS)
replaces this later. Keeping this simple makes the validation trustworthy.
"""
from __future__ import annotations
import numpy as np
from scipy.signal import butter, filtfilt, detrend


def _select_sensitive_subcarrier(amp: np.ndarray) -> int:
    """Pick the subcarrier with the largest temporal variance (most modulated)."""
    return int(np.argmax(np.var(amp, axis=0)))


def bandpass(x: np.ndarray, fs: float, lo: float, hi: float, order: int = 4) -> np.ndarray:
    """Zero-phase Butterworth bandpass."""
    nyq = fs / 2.0
    lo_n = max(lo / nyq, 1e-4)
    hi_n = min(hi / nyq, 0.99)
    b, a = butter(order, [lo_n, hi_n], btype="band")
    return filtfilt(b, a, x)


def estimate_rate(
    result,
    band: tuple[float, float] = (0.1, 0.6),
    subcarrier: int | None = None,
    use: str = "amplitude",
) -> dict:
    """
    Estimate a periodic rate (in BPM) from a CSIResult.

    band : frequency search band in Hz. Breathing ~ (0.1, 0.6),
           heartbeat ~ (0.8, 2.0).
    use  : 'amplitude' or 'phase' time series.
    Returns dict with estimated bpm, peak frequency, and the spectrum.
    """
    fs = result.config.sample_rate
    sig_full = result.amplitude if use == "amplitude" else np.unwrap(result.phase, axis=0)

    k = subcarrier if subcarrier is not None else _select_sensitive_subcarrier(sig_full)
    x = sig_full[:, k].astype(float)
    x = detrend(x)

    # Bandpass to the physiological band, then DFT
    try:
        xf = bandpass(x, fs, band[0], band[1])
    except ValueError:
        xf = x  # if too short, skip filtering

    n = len(xf)
    window = np.hanning(n)
    # Zero-pad to a large FFT length to finely interpolate the spectrum,
    # so frequency resolution is not limited by the record duration.
    nfft = max(1 << 16, 1 << int(np.ceil(np.log2(n)) + 3))
    spectrum = np.abs(np.fft.rfft(xf * window, n=nfft))
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)

    # Restrict peak search to the band
    mask = (freqs >= band[0]) & (freqs <= band[1])
    if not mask.any():
        return {"bpm": None, "peak_hz": None, "subcarrier": k,
                "freqs": freqs, "spectrum": spectrum}

    peak_idx = np.argmax(spectrum * mask)
    peak_hz = float(freqs[peak_idx])

    return {
        "bpm": peak_hz * 60.0,
        "peak_hz": peak_hz,
        "subcarrier": k,
        "freqs": freqs,
        "spectrum": spectrum,
    }
