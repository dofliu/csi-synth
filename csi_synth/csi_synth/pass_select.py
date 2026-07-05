"""
pass_select.py — Posture-Aware Subcarrier Selection (PASS), thesis contribution C2.

The problem PASS solves (the physics):
    Which subcarriers carry the breathing signal is set by where the static and
    person-scattered paths interfere:  S_k ≈ |H_d(f_k)| · |sin(∠H_s(f_k) − ∠H_d(f_k))|
    (max when orthogonal, zero when collinear — the Fresnel blind spot). When a
    sleeper TURNS OVER, the chest moves and re-orients, so the scatter path length
    and geometry change → the SET of breathing-sensitive subcarriers SHIFTS. A
    detector that commits to one fixed subcarrier set (chosen while supine) loses
    signal after a turn and its breathing-rate error blows up.

PASS is a three-step online mechanism:
    1. Turn detection      — a posture change shows up as a burst of frame-to-frame
                             CSI motion; detect_transitions() finds these bursts.
    2. Posture fingerprint — between turns the static channel |H(f_k)| profile is a
                             stable per-posture signature; classify_posture() matches
                             it (nearest-centroid) to a learned posture.
    3. Re-selection        — load that posture's pre-learned sensitive subcarriers
                             (or re-select on the fly), restoring the fused SNR_eff.

This module holds the REUSABLE primitives (selection, turn detection, fingerprint
classification, fused estimation/SNR) plus a PASSTracker that runs the online loop.
The experiment that quantifies the gain lives in pass_analysis.py.

Honesty: synthetic CSI validates the METHOD and the relative ordering
(fixed < PASS ≤ oracle), not absolute clinical accuracy. Re-validate on real
AX211 captures.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np

FS_DEFAULT = 20.0
BREATH_BAND = (0.15, 0.6)     # Hz — resting respiration
_BIN = 0.025                  # Hz — DFT bin spacing (matches the rest of csi_synth)


# ───────────────────────── subcarrier sensitivity ─────────────────────────
def band_energy_per_subcarrier(amp: np.ndarray, fs: float = FS_DEFAULT,
                               band: tuple = BREATH_BAND) -> np.ndarray:
    """
    Per-subcarrier breathing-band energy — the empirical proxy for S_k.

    amp : (T, N) amplitude time series. Returns (N,) energy vector.
    """
    amp = np.asarray(amp, dtype=float)
    T = amp.shape[0]
    x = amp - amp.mean(axis=0, keepdims=True)
    n = np.arange(T)
    lo = max(1, int(round(band[0] / _BIN)))
    hi = int(round(band[1] / _BIN))
    e = np.zeros(amp.shape[1])
    for fi in range(lo, hi + 1):
        f = fi * _BIN
        c = np.cos(2 * np.pi * f / fs * n)
        s = np.sin(2 * np.pi * f / fs * n)
        re = x.T @ c
        im = -(x.T @ s)
        e += np.hypot(re, im) / T
    return e


def select_sensitive(amp: np.ndarray, k: int = 8, fs: float = FS_DEFAULT,
                     band: tuple = BREATH_BAND) -> np.ndarray:
    """Return indices of the top-k breathing-sensitive subcarriers."""
    e = band_energy_per_subcarrier(amp, fs, band)
    k = min(k, e.size)
    return np.argsort(e)[::-1][:k]


def estimate_rate_subs(amp: np.ndarray, subs, fs: float = FS_DEFAULT,
                       band: tuple = BREATH_BAND) -> float:
    """Estimate breathing rate (BPM) by fusing the chosen subcarriers' spectra."""
    amp = np.asarray(amp, dtype=float)
    subs = np.asarray(subs)
    T = amp.shape[0]
    x = amp[:, subs] - amp[:, subs].mean(axis=0, keepdims=True)
    n = np.arange(T)
    lo = max(1, int(round(band[0] / _BIN)))
    hi = int(round(band[1] / _BIN))
    best_f, best_mag = lo * _BIN, -1.0
    for fi in range(lo, hi + 1):
        f = fi * _BIN
        re = np.sum(x.T * np.cos(2 * np.pi * f / fs * n), axis=1)
        im = -np.sum(x.T * np.sin(2 * np.pi * f / fs * n), axis=1)
        mag = float(np.mean(np.hypot(re, im)) / T)
        if mag > best_mag:
            best_mag, best_f = mag, f
    return best_f * 60.0


def fused_snr_eff(amp: np.ndarray, subs, fs: float = FS_DEFAULT,
                  band: tuple = BREATH_BAND) -> float:
    """
    Fused breathing-band SNR_eff for a subcarrier set: peak breathing-band
    magnitude of the averaged spectrum over an out-of-band (>0.75 Hz) noise floor.
    Directly reflects SNR_eff ∝ (Σ S_k)² / (M σ²).
    """
    amp = np.asarray(amp, dtype=float)
    subs = np.asarray(subs)
    T = amp.shape[0]
    x = amp[:, subs] - amp[:, subs].mean(axis=0, keepdims=True)
    n = np.arange(T)

    def band_mag(f):
        re = np.sum(x.T * np.cos(2 * np.pi * f / fs * n), axis=1)
        im = -np.sum(x.T * np.sin(2 * np.pi * f / fs * n), axis=1)
        return float(np.mean(np.hypot(re, im)) / T)

    lo = max(1, int(round(band[0] / _BIN)))
    hi = int(round(band[1] / _BIN))
    peak = max(band_mag(fi * _BIN) for fi in range(lo, hi + 1))
    noise_bins = [fi * _BIN for fi in range(int(0.75 / _BIN), int(1.5 / _BIN) + 1)]
    noise = np.mean([band_mag(f) for f in noise_bins]) + 1e-12
    return peak / noise


# ───────────────────────── turn (posture-change) detection ─────────────────────────
def _smooth_time(amp: np.ndarray, win: int) -> np.ndarray:
    """Causal-symmetric moving-average along time (axis 0) to suppress AWGN."""
    if win <= 1:
        return amp
    k = np.ones(win) / win
    pad = win // 2
    ap = np.pad(amp, ((pad, pad), (0, 0)), mode="edge")
    out = np.empty_like(amp)
    for j in range(amp.shape[1]):
        out[:, j] = np.convolve(ap[:, j], k, mode="valid")[: amp.shape[0]]
    return out


def motion_series(amp: np.ndarray, fs: float = FS_DEFAULT,
                  smooth_s: float = 0.5) -> np.ndarray:
    """
    Frame-to-frame normalized CSI activity (T,) — bursts mark posture changes.

    Bulk-body (turn) motion is low-frequency while thermal/AWGN is high-frequency,
    so we smooth each subcarrier over ~smooth_s before differencing. This makes the
    turn burst stand out from the noise floor at low SNR (raw differencing does not).
    """
    amp = np.asarray(amp, dtype=float)
    sm = _smooth_time(amp, max(1, int(round(smooth_s * fs))))
    d = np.abs(np.diff(sm, axis=0)).mean(axis=1)
    d = d / (np.abs(sm).mean() + 1e-12)
    return np.concatenate([[0.0], d])


def detect_transitions(amp: np.ndarray, fs: float = FS_DEFAULT,
                       thresh_mult: float = 5.0, min_gap_s: float = 2.5) -> list:
    """
    Detect posture-change (turn) events as bursts of frame-to-frame motion.

    Returns a list of event dicts {start, end, center} in FRAME indices, merged
    if closer than min_gap_s. Robust threshold = median + thresh_mult·MAD.
    """
    m = motion_series(amp, fs=fs)
    base = np.median(m)
    mad = np.median(np.abs(m - base)) + 1e-12
    thr = base + thresh_mult * 1.4826 * mad
    hot = m > thr

    events = []
    i, T = 0, m.size
    gap = int(round(min_gap_s * fs))
    while i < T:
        if hot[i]:
            j = i
            while j + 1 < T and (hot[j + 1] or np.any(hot[j + 1:min(T, j + 1 + gap)])):
                j += 1
            events.append({"start": i, "end": j, "center": (i + j) // 2})
            i = j + 1
        else:
            i += 1
    return events


def stable_segments(n_frames: int, transitions: list, fs: float = FS_DEFAULT,
                    settle_s: float = 1.5) -> list:
    """
    Split [0, n_frames) into stable (non-turning) segments BETWEEN detected turns,
    dropping a settle margin after each turn. Returns list of (start, end) frames.
    """
    settle = int(round(settle_s * fs))
    cuts = [0]
    for ev in transitions:
        cuts.append(ev["start"])
        cuts.append(min(n_frames, ev["end"] + settle))
    cuts.append(n_frames)
    segs = []
    for a, b in zip(cuts[0::2], cuts[1::2]):
        if b - a > int(round(2.0 * fs)):     # keep only usefully long segments
            segs.append((int(a), int(b)))
    return segs


# ───────────────────────── posture fingerprint + classification ─────────────────────────
def posture_fingerprint(amp: np.ndarray, fs: float = FS_DEFAULT,
                        band: tuple = BREATH_BAND) -> np.ndarray:
    """
    Posture signature = the PATTERN of breathing sensitivity across subcarriers,
    unit-normalized. We deliberately do NOT use the raw |H| amplitude profile: that
    is dominated by the static room channel (walls/direct path), which is identical
    for every posture. The posture-specific information lives in the person-scatter
    term, which is exactly what the breathing-band energy profile isolates — so this
    signature is both discriminative between postures and stable within one.
    """
    amp = np.asarray(amp, dtype=float)
    prof = band_energy_per_subcarrier(amp, fs, band)
    prof = np.log(prof + 1e-9)
    prof = prof - prof.mean()
    nrm = np.linalg.norm(prof) + 1e-12
    return prof / nrm


def classify_posture(fp: np.ndarray, centroids: dict) -> str:
    """Nearest-centroid posture classification by cosine similarity."""
    best_key, best_sim = None, -np.inf
    for key, c in centroids.items():
        sim = float(np.dot(fp, c) / (np.linalg.norm(c) + 1e-12))
        if sim > best_sim:
            best_sim, best_key = sim, key
    return best_key


# ───────────────────────── learned PASS profile + online tracker ─────────────────────────
@dataclass
class PostureProfile:
    """Per-posture knowledge learned once during (clean) calibration."""
    fingerprint: np.ndarray            # static-channel signature (for classification)
    subcarriers: np.ndarray            # this posture's sensitive subcarrier set


def learn_posture_profiles(calib: dict, k: int = 8, fs: float = FS_DEFAULT,
                           band: tuple = BREATH_BAND) -> dict:
    """
    Learn one PostureProfile per posture from clean calibration windows.

    calib : {posture_key: amp (T,N)}  (or {key: list-of-amp}).
    Returns {posture_key: PostureProfile}.
    """
    profiles = {}
    for key, data in calib.items():
        wins = data if isinstance(data, (list, tuple)) else [data]
        fp = np.mean([posture_fingerprint(w) for w in wins], axis=0)
        en = np.mean([band_energy_per_subcarrier(w, fs, band) for w in wins], axis=0)
        subs = np.argsort(en)[::-1][:k]
        profiles[key] = PostureProfile(fingerprint=fp, subcarriers=subs)
    return profiles


@dataclass
class PASSTracker:
    """
    Online PASS: on each stable window, classify posture from its fingerprint and
    switch to that posture's sensitive subcarriers. Falls back to on-the-fly
    re-selection when no matching profile is confident enough.

    profiles : {posture_key: PostureProfile} from learn_posture_profiles().
    """
    profiles: dict
    k: int = 8
    fs: float = FS_DEFAULT
    band: tuple = BREATH_BAND
    current_posture: Optional[str] = None
    current_subs: Optional[np.ndarray] = None
    history: list = field(default_factory=list)

    def _centroids(self):
        return {key: p.fingerprint for key, p in self.profiles.items()}

    def update(self, amp_window: np.ndarray) -> np.ndarray:
        """
        Ingest one stable window; (re)select subcarriers for its posture.
        Returns the subcarrier set to use for this window.
        """
        fp = posture_fingerprint(amp_window)
        posture = classify_posture(fp, self._centroids()) if self.profiles else None
        if posture is not None and posture in self.profiles:
            subs = self.profiles[posture].subcarriers
        else:                                   # unknown posture → adapt on the fly
            subs = select_sensitive(amp_window, self.k, self.fs, self.band)
        self.current_posture, self.current_subs = posture, subs
        self.history.append({"posture": posture, "subs": np.asarray(subs)})
        return subs

    def estimate(self, amp_window: np.ndarray) -> dict:
        """Classify + re-select + estimate breathing rate for one stable window."""
        subs = self.update(amp_window)
        bpm = estimate_rate_subs(amp_window, subs, self.fs, self.band)
        snr = fused_snr_eff(amp_window, subs, self.fs, self.band)
        return {"posture": self.current_posture, "subcarriers": subs,
                "bpm": bpm, "snr_eff": snr}
