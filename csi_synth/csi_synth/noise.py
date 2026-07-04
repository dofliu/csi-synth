"""
noise.py — Optional hardware-impairment and noise layer.

The clean CSI from generator.py is physically ideal. Real CSI captured from
an Intel AX211 (or ESP32) is corrupted by several well-known effects. This
module applies them ON TOP of the clean signal, so you can dial realism up
or down and test how robust your preprocessing / model is.

Impairments modelled (all toggleable):
    - AWGN            : thermal/receiver noise (set by target SNR in dB)
    - CFO             : carrier frequency offset -> linear phase drift over time
    - SFO             : sampling frequency offset -> phase slope across subcarriers
    - amplitude AGC   : slow random gain fluctuation (automatic gain control)
    - phase jitter    : random per-packet phase noise

References for why these matter: Ratnam et al. 2024 (IEEE TWC) on CSI
preprocessing; standard OFDM impairment models.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

from .generator import CSIResult


@dataclass
class NoiseConfig:
    enable: bool = True
    snr_db: float = 25.0            # target signal-to-noise ratio (AWGN)
    cfo_hz: float = 200.0           # carrier freq offset (Hz); 0 to disable
    sfo_ppm: float = 5.0            # sampling freq offset (parts per million)
    agc_std: float = 0.03          # std of slow multiplicative gain drift
    phase_jitter_std: float = 0.02  # rad, per-packet random phase
    seed: int | None = None


def apply_noise(result: CSIResult, cfg: NoiseConfig | None = None) -> CSIResult:
    """
    Return a NEW CSIResult with impairments applied. The original clean
    result is left untouched (useful for before/after comparison).
    """
    cfg = cfg or NoiseConfig()
    if not cfg.enable:
        return result

    rng = np.random.default_rng(cfg.seed)
    csi = result.csi.copy()
    n_time, n_sub = csi.shape
    t = result.t
    freqs = result.freqs

    # --- CFO: phase term e^{j 2 pi cfo t}, common to all subcarriers ---
    if cfg.cfo_hz:
        cfo_phase = np.exp(1j * 2 * np.pi * cfg.cfo_hz * t)  # (n_time,)
        csi = csi * cfo_phase[:, None]

    # --- SFO: phase slope across subcarriers growing with time ---
    if cfg.sfo_ppm:
        # subcarrier index centred
        k = np.arange(n_sub) - n_sub / 2
        # phase slope proportional to ppm, subcarrier index and time
        sfo = cfg.sfo_ppm * 1e-6
        sfo_phase = np.exp(1j * 2 * np.pi * sfo * np.outer(t * result.config.sample_rate, k) * 0.01)
        csi = csi * sfo_phase

    # --- AGC: slow random multiplicative gain drift ---
    # Real AGC drift is much slower than breathing. Generate white noise and
    # low-pass heavily (moving average) so its energy sits below ~0.05 Hz and
    # does not masquerade as a breathing peak.
    if cfg.agc_std:
        raw = rng.normal(0, cfg.agc_std, n_time)
        win = max(1, int(result.config.sample_rate * 8))  # ~8 s smoothing
        kernel = np.ones(win) / win
        drift = np.convolve(raw.cumsum(), kernel, mode="same")
        drift = drift - drift.mean()
        drift = drift / (np.abs(drift).max() + 1e-9) * cfg.agc_std * 3
        gain = 1.0 + drift
        csi = csi * gain[:, None]

    # --- Per-packet phase jitter ---
    if cfg.phase_jitter_std:
        jitter = rng.normal(0, cfg.phase_jitter_std, n_time)
        csi = csi * np.exp(1j * jitter)[:, None]

    # --- AWGN to hit a target SNR ---
    if cfg.snr_db is not None:
        sig_power = np.mean(np.abs(csi) ** 2)
        snr_lin = 10 ** (cfg.snr_db / 10)
        noise_power = sig_power / snr_lin
        noise = (rng.normal(0, np.sqrt(noise_power / 2), csi.shape)
                 + 1j * rng.normal(0, np.sqrt(noise_power / 2), csi.shape))
        csi = csi + noise

    lbl = dict(result.label)
    lbl["noise"] = {
        "snr_db": cfg.snr_db, "cfo_hz": cfg.cfo_hz, "sfo_ppm": cfg.sfo_ppm,
        "agc_std": cfg.agc_std, "phase_jitter_std": cfg.phase_jitter_std,
    }
    return CSIResult(csi=csi, t=result.t, freqs=result.freqs,
                     label=lbl, config=result.config)
