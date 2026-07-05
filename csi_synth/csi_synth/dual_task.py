"""
dual_task.py — Dual-task vital-sign model (thesis contribution C3), NumPy core.

C3 is a lightweight model that does TWO jobs at once from a CSI window:
    (1) breathing-rate REGRESSION  (BPM)
    (2) respiratory-event CLASSIFICATION  {normal, hypopnea, OSA, CSA}
trained with a combined objective  L = α·L_reg + β·L_cls.

Why one shared model: the two tasks share features (the respiratory waveform and
its collapse), and the classification head is what lets the system catch the
events a motion-only detector misses — obstructive apnea (effort continues) and
hypopnea (effort merely reduced), the two clinically dominant, hardest events.

This module provides:
  * make_dataset()  — labelled CSI windows from the clinical effort model
                      (per-window: raw sequence, hand features, rate, event, and
                      a MOTION-ONLY prediction for the clinical comparison).
  * window_features() — compact per-window features for the NumPy baseline.
  * DualTaskMLP     — a small, fully-NumPy dual-task model (manual backprop) that
                      RUNS and is TESTABLE here (weighted CE + smooth-L1). It is
                      the runnable stand-in / baseline; the thesis BiLSTM with a
                      focal objective lives in dual_task_torch.py for the GPU.
  * motion_only_predict() — the naive "motion stops = apnea" detector.

Honesty: trained/validated on SYNTHETIC CSI — proves the pipeline and the
relative ordering (dual-task catches OSA/hypopnea that motion-only misses). All
numbers must be re-validated on real annotated AX211 recordings.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

from .generator import RadioConfig
from .geometry import Room, Node
from .clinical import (SleepBreathingModel, ClinicalEvent, generate_clinical_csi,
                       NORMAL, HYPOPNEA, APNEA_OSA, APNEA_CSA, EVENT_NAMES)

FS = 20.0
WIN_S = 24.0                       # window length (s): 12 s baseline + 12 s event
N_SUB = 64
N_CLASS = 4
CFG = RadioConfig(n_subcarriers=N_SUB, sample_rate=FS)
_ROOM = Room(5.0, 4.0)
_TX, _RX = Node(0.6, 2.0), Node(4.4, 2.0)
_BED = (2.5, 2.0)
# small posture jitter near the bed centre. Posture ROBUSTNESS is PASS's job (C2);
# here we isolate the C3 tasks (rate regression + event classification).
_POS = [(0.0, 0.0), (0.05, 0.05), (-0.05, 0.06), (0.04, -0.05)]


# ── window layout: a NORMAL baseline then the event, so a detector sees the CHANGE
#    (real scoring is baseline-relative; a uniform window hides amplitude reductions).
#    12 s baseline is long enough to estimate the breathing rate reliably (~0.5 BPM). ──
BASE_S, EVT_START = 12.0, 12.0      # baseline 0–12 s (rate + level); event 12–24 s


def _one_window(event_kind, rate_bpm, pos, snr, seed):
    """Generate one WIN_S window: normal baseline → event → amplitude (T,N), mask (T)."""
    dx, dy = pos
    # modest cycle variability: realistic but keeps the nominal rate label ≈ realized
    # breathing frequency (large drift would make the regression target itself noisy).
    model = SleepBreathingModel(rate_bpm=rate_bpm, amplitude_mm=5.0,
                                period_cv=0.03, amp_cv=0.06, seed=seed)
    events = [] if event_kind == NORMAL else [ClinicalEvent(event_kind, EVT_START, WIN_S - EVT_START)]
    amp, mask, _ = generate_clinical_csi(_ROOM, _TX, Node(_RX.x + dx, _RX.y + dy),
                                         (_BED[0], _BED[1]), model, events,
                                         duration=WIN_S, radio=CFG, snr_db=snr, seed=seed)
    return amp, mask


def _band_energy(amp, fs=FS):
    """Per-subcarrier breathing-band energy (S_k proxy)."""
    T = amp.shape[0]
    x = amp - amp.mean(0, keepdims=True)
    n = np.arange(T)
    e = np.zeros(amp.shape[1])
    for fi in range(6, 25):
        f = fi * 0.025
        e += np.hypot(x.T @ np.cos(2 * np.pi * f / fs * n),
                      x.T @ np.sin(2 * np.pi * f / fs * n)) / T
    return e


def _seg_breathing(seg, ks, fs=FS):
    """
    Fused breathing (peak magnitude, peak freq Hz, SNR) over a set of subcarriers.
    Averaging the spectra of the top-K subcarriers suppresses per-subcarrier noise,
    giving a much more stable rate/level estimate than a single best subcarrier.
    """
    n = np.arange(seg.shape[0])
    cols = seg[:, ks] - seg[:, ks].mean(0, keepdims=True)
    freqs = np.arange(0.15, 0.55, 0.005)      # fine grid → 0.3 BPM, not 1.5 BPM, resolution
    mags = np.empty(freqs.size)
    for j, f in enumerate(freqs):
        re = cols.T @ np.cos(2 * np.pi * f / fs * n)
        im = cols.T @ np.sin(2 * np.pi * f / fs * n)
        mags[j] = np.mean(np.hypot(re, im)) / seg.shape[0]
    i = int(np.argmax(mags))
    snr = mags[i] / (np.median(mags) + 1e-9)
    return float(mags[i]), float(freqs[i]), float(snr)


def window_features(amp, fs=FS):
    """
    Baseline-relative per-window features for the dual task. The event is scored
    against the window's own normal baseline, which is what makes hypopnea (partial
    drop) and CSA (full stop) visible. OSA (effort continues) stays close to normal
    on single-link amplitude — the honest hard case (needs the thoraco-abdominal
    paradox, i.e. phase / MIMO). Feature order is fixed (see FEATURE_NAMES).
    """
    ks = np.argsort(_band_energy(amp, fs))[::-1][:6]
    b0, b1 = amp[:int(BASE_S * fs)], amp[int(EVT_START * fs):]
    e_base, f_base, snr_base = _seg_breathing(b0, ks, fs)
    e_evt, f_evt, snr_evt = _seg_breathing(b1, ks, fs)
    drop = e_evt / (e_base + 1e-9)                       # ~1 normal/OSA, ~0.4 hypo, ~0 CSA
    # cross-subcarrier breathing coherence in the event segment
    cols = [b1[:, kk] - b1[:, kk].mean() for kk in ks]
    C = np.corrcoef(cols)
    coh = float(C[np.triu_indices(len(ks), 1)].mean())
    var_base = float(np.var(b0[:, ks[0]] - b0[:, ks[0]].mean()))
    feats = np.array([f_base, snr_base, snr_evt, drop, coh,
                      np.log(var_base + 1e-12), e_base, e_evt], dtype=float)
    return feats


FEATURE_NAMES = ["peak_f_base", "br_snr_base", "br_snr_evt", "drop_ratio",
                 "coherence_evt", "log_var_base", "energy_base", "energy_evt"]
_DROP_IDX = 3


def motion_only_predict(feats):
    """
    Naive 'motion stops ⇒ apnea' detector (the C4 baseline). Flags an event only
    when breathing MOTION collapses to near zero (CSA). Hypopnea keeps reduced-but-
    present motion and OSA keeps full effort, so this detector MISSES both — exactly
    the clinical blind spot the dual-task classifier is meant to cover.
    Returns a class in {NORMAL, APNEA_CSA}.
    """
    return APNEA_CSA if feats[_DROP_IDX] < 0.30 else NORMAL


def make_dataset(per_class=120, seed=0):
    """
    Build a labelled window dataset spanning the four event classes, varied over
    rate, posture and SNR. Returns a dict of arrays (deterministic given seed).
    """
    rng = np.random.default_rng(seed)
    X_feat, X_seq, y_rate, y_event, motion = [], [], [], [], []
    classes = [NORMAL, HYPOPNEA, APNEA_OSA, APNEA_CSA]
    sub_sel = None
    s = seed * 100003 + 1
    for cls in classes:
        for _ in range(per_class):
            rate = float(rng.uniform(11, 20))
            pos = _POS[int(rng.integers(len(_POS)))]
            snr = float(rng.uniform(14, 24))
            amp, _mask = _one_window(cls, rate, pos, snr, seed=s); s += 1
            if sub_sel is None:                      # fix the 16 sequence subcarriers once
                sub_sel = np.argsort(_band_energy(amp))[::-1][:16]
            feats = window_features(amp)
            X_feat.append(feats)
            X_seq.append(amp[::2, sub_sel])          # (T/2, 16) sequence for the RNN
            y_rate.append(rate)
            y_event.append(cls)
            motion.append(motion_only_predict(feats))
    return dict(
        X_feat=np.array(X_feat), X_seq=np.array(X_seq),
        y_rate=np.array(y_rate), y_event=np.array(y_event, dtype=int),
        motion_pred=np.array(motion, dtype=int), sub_sel=sub_sel)


# ───────────────────────── NumPy dual-task MLP (runnable baseline) ─────────────────────────
def _standardize_fit(X):
    mu = X.mean(0); sd = X.std(0) + 1e-9
    return mu, sd


@dataclass
class DualTaskMLP:
    """
    A small dual-task model on window features (fully NumPy, manual backprop):
        h = tanh(X·W1 + b1)
        rate  = h·Wr + br                (regression head)
        logit = h·Wc + bc  → softmax     (4-class event head)
    Objective  L = α·SmoothL1(rate) + β·weighted-CE(event). The GPU BiLSTM in
    dual_task_torch.py replaces the CE with the thesis's focal loss; the ordering
    (dual-task ≫ motion-only on OSA/hypopnea) is what this baseline verifies.
    """
    hidden: int = 32
    alpha: float = 1.0
    beta: float = 1.0
    lr: float = 0.1
    epochs: int = 1200
    seed: int = 0
    # fitted state
    W1: np.ndarray = field(default=None, repr=False)
    b1: np.ndarray = field(default=None, repr=False)
    Wr: np.ndarray = field(default=None, repr=False)
    br: float = 0.0
    Wc: np.ndarray = field(default=None, repr=False)
    bc: np.ndarray = field(default=None, repr=False)
    _mu: np.ndarray = field(default=None, repr=False)
    _sd: np.ndarray = field(default=None, repr=False)
    _rmu: float = 0.0
    _rsd: float = 1.0
    class_w: np.ndarray = field(default=None, repr=False)

    def _init(self, D):
        rng = np.random.default_rng(self.seed)
        H = self.hidden
        self.W1 = rng.normal(0, 1 / np.sqrt(D), (D, H))
        self.b1 = np.zeros(H)
        self.Wr = rng.normal(0, 1 / np.sqrt(H), (H, 1))
        self.br = 0.0
        self.Wc = rng.normal(0, 1 / np.sqrt(H), (H, N_CLASS))
        self.bc = np.zeros(N_CLASS)

    def _forward(self, Xs):
        z1 = Xs @ self.W1 + self.b1
        h = np.tanh(z1)
        rate = (h @ self.Wr).ravel() + self.br
        logit = h @ self.Wc + self.bc
        logit -= logit.max(1, keepdims=True)
        p = np.exp(logit); p /= p.sum(1, keepdims=True)
        return h, rate, p

    def _backward(self, Xs, yr, ye):
        """One forward+backward on standardized inputs; returns (loss, grads dict)."""
        N = Xs.shape[0]
        Y = np.eye(N_CLASS)[ye]
        wvec = self.class_w[ye]
        h, rate, p = self._forward(Xs)
        # regression: smooth-L1 on standardized rate
        diff = rate - yr
        l_reg = np.mean(np.where(np.abs(diff) < 1.0, 0.5 * diff ** 2, np.abs(diff) - 0.5))
        dr = np.where(np.abs(diff) < 1.0, diff, np.sign(diff)) / N * self.alpha
        # classification: weighted cross-entropy
        l_cls = np.mean(-wvec * np.log(p[np.arange(N), ye] + 1e-12))
        dlog = (p - Y) * wvec[:, None] / N * self.beta
        g = {}
        g["Wr"] = h.T @ dr[:, None]
        g["br"] = dr.sum()
        g["Wc"] = h.T @ dlog
        g["bc"] = dlog.sum(0)
        dh = dr[:, None] @ self.Wr.T + dlog @ self.Wc.T
        dz1 = dh * (1 - h ** 2)
        g["W1"] = Xs.T @ dz1
        g["b1"] = dz1.sum(0)
        return self.alpha * l_reg + self.beta * l_cls, g

    def fit(self, X, y_rate, y_event):
        D = X.shape[1]
        self._mu, self._sd = _standardize_fit(X)
        self._rmu, self._rsd = float(y_rate.mean()), float(y_rate.std() + 1e-9)
        Xs = (X - self._mu) / self._sd
        yr = (y_rate - self._rmu) / self._rsd
        # inverse-frequency class weights (events are the minority that matters)
        counts = np.bincount(y_event, minlength=N_CLASS).astype(float)
        self.class_w = (counts.sum() / (N_CLASS * (counts + 1e-9)))
        self._init(D)
        for _ in range(self.epochs):
            _, g = self._backward(Xs, yr, y_event)
            self.W1 -= self.lr * g["W1"]; self.b1 -= self.lr * g["b1"]
            self.Wr -= self.lr * g["Wr"]; self.br -= self.lr * g["br"]
            self.Wc -= self.lr * g["Wc"]; self.bc -= self.lr * g["bc"]
        return self

    def predict(self, X):
        Xs = (X - self._mu) / self._sd
        _, rate, p = self._forward(Xs)
        return rate * self._rsd + self._rmu, p.argmax(1)

    def loss(self, X, y_rate, y_event):
        """Combined objective value (for gradient-checking / monitoring)."""
        Xs = (X - self._mu) / self._sd
        yr = (y_rate - self._rmu) / self._rsd
        _, rate, p = self._forward(Xs)
        diff = np.abs(rate - yr)
        l_reg = np.mean(np.where(diff < 1.0, 0.5 * diff ** 2, diff - 0.5))
        wvec = self.class_w[y_event]
        l_cls = np.mean(-wvec * np.log(p[np.arange(len(y_event)), y_event] + 1e-12))
        return self.alpha * l_reg + self.beta * l_cls
