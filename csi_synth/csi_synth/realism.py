"""
realism.py — Physical-realism layer for csi_synth.

The clean core (generator.py) uses an idealized model: a single point
scatterer whose thorax moves as a pure sinusoid, with purely specular
multipath. Real CSI departs from this in several systematic ways, all of
which make the sensing problem HARDER. This module adds those effects as an
optional layer so their individual impact can be measured (see
realism_analysis.py). Each factor can be toggled independently.

Realism factors modeled here, with physical justification:

1. Extended, multi-segment body.
   A human is not a point. The thorax and abdomen move quasi-independently
   (thoraco-abdominal motion), with the abdomen typically leading slightly
   in diaphragmatic breathing and desynchronizing under obstructive load.
   We model K scattering centers at distinct positions with individual
   excursions and phase offsets.

2. Physiological respiration waveform.
   Real breathing is not sinusoidal: inhalation is faster than exhalation
   (I:E ratio ~1:2), and both period and depth vary cycle-to-cycle. This
   variability is the dominant source of false alarms in apnea detection,
   so an honest twin must include it.

3. Diffuse (rough-surface) scattering via a Rician model.
   Specular image-source reflections are an idealization; real surfaces are
   rough and produce a diffuse component. We split the channel into a
   specular part (weight sqrt(K/(K+1))) and a complex-Gaussian diffuse part
   (weight sqrt(1/(K+1))), where the Rician K-factor (dB) controls richness.
   Lower K => richer multipath => harder.

4. Structured background micro-motion.
   The environment is never perfectly static: curtains, HVAC airflow, and
   other reflectors drift slowly, adding low-frequency, non-white structure
   that a white-noise model omits.

IMPORTANT: this layer increases realism but remains a model. It is for
quantifying which idealizations matter and for stress-testing algorithms;
it does not replace measured data.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

from .geometry import Room, Node
from .generator import RadioConfig, CSIResult, C


# ───────────────────────── respiration waveform ─────────────────────────
@dataclass
class RespirationModel:
    rate_bpm: float = 15.0
    amplitude_mm: float = 5.0
    ie_ratio: float = 0.40          # inhale fraction of cycle (0.4 => 1:1.5)
    period_cv: float = 0.08         # cycle-to-cycle period coeff. of variation
    amp_cv: float = 0.10            # cycle-to-cycle amplitude coeff. of variation
    sinusoidal: bool = False        # if True, revert to a pure sinusoid
    seed: int | None = None

    def displacement(self, t: np.ndarray) -> np.ndarray:
        """Radial chest displacement (metres) at times t (s)."""
        a = self.amplitude_mm * 1e-3
        if self.sinusoidal:
            f = self.rate_bpm / 60.0
            return a * np.sin(2 * np.pi * f * t)

        rng = np.random.default_rng(self.seed)
        f0 = self.rate_bpm / 60.0
        dt = t[1] - t[0] if len(t) > 1 else 1.0 / 20
        # instantaneous frequency with smooth cycle-to-cycle variability
        n = len(t)
        # per-sample smooth random modulation of rate
        drift = rng.normal(0, self.period_cv, n).cumsum()
        drift = np.convolve(drift, np.ones(int(1/f0/dt) or 1) / (int(1/f0/dt) or 1), mode="same")
        drift -= drift.mean()
        inst_f = f0 * (1.0 + np.clip(drift, -0.5, 0.5))
        phase = 2 * np.pi * np.cumsum(inst_f) * dt
        cycle = (phase / (2 * np.pi)) % 1.0
        # amplitude modulation per cycle (slow)
        amp_mod = 1.0 + self.amp_cv * np.sin(2 * np.pi * 0.03 * t + rng.uniform(0, 6.28))
        # asymmetric inhale/exhale shape mapped from cycle position in [0,1)
        r = self.ie_ratio
        d = np.where(
            cycle < r,
            0.5 * (1 - np.cos(np.pi * cycle / r)),          # inhale (rising)
            0.5 * (1 + np.cos(np.pi * (cycle - r) / (1 - r)))  # exhale (falling)
        )
        # center around zero, scale to amplitude
        return a * amp_mod * (d - 0.5) * 2.0


# ───────────────────────── extended body ─────────────────────────
@dataclass
class BodySegment:
    dx: float           # position offset from body centre (m)
    dy: float
    excursion: float    # relative excursion scale (1.0 = full amplitude)
    phase: float        # phase offset (rad); abdomen may lead/lag thorax
    xsec: float         # scattering cross-section weight


def default_body(async_level: float = 0.0) -> list[BodySegment]:
    """
    Thorax + abdomen (+ two limbs). `async_level` (0..1) adds thoraco-
    abdominal phase desynchronization, as seen under obstructive load.
    """
    return [
        BodySegment(dx=0.0,  dy=-0.12, excursion=1.00, phase=0.0,                  xsec=0.55),  # thorax
        BodySegment(dx=0.0,  dy=+0.10, excursion=0.85, phase=0.3 + 2.5*async_level, xsec=0.45),  # abdomen
        BodySegment(dx=-0.18, dy=0.0,  excursion=0.10, phase=0.0,                  xsec=0.10),  # left arm (mostly static)
        BodySegment(dx=+0.18, dy=0.0,  excursion=0.10, phase=0.0,                  xsec=0.10),  # right arm
    ]


@dataclass
class RealismConfig:
    extended_body: bool = True
    async_level: float = 0.0        # 0 normal .. 1 strong thoraco-abdominal asynchrony
    respiration_variability: bool = True
    diffuse: bool = True
    rician_k_db: float = 8.0        # lower => richer diffuse multipath => harder
    background_motion: bool = True
    background_level: float = 0.02  # relative strength of environmental drift
    seed: int | None = None


def _dist(a, b):
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


def generate_csi_realistic(
    room: Room, tx: Node, rx: Node, body_xy,
    resp: RespirationModel, cfg: RealismConfig,
    duration: float = 30.0, radio: RadioConfig | None = None,
    present: bool = True, label: dict | None = None,
) -> CSIResult:
    """
    Realistic CSI generation. `body_xy` = (x, y) centre of the person.
    Adds extended body, physiological respiration, Rician diffuse scattering
    and structured background on top of the specular multipath.
    """
    radio = radio or RadioConfig()
    freqs = radio.subcarrier_freqs
    nt = int(round(duration * radio.sample_rate))
    t = np.arange(nt) / radio.sample_rate
    rng = np.random.default_rng(cfg.seed)

    # respiration waveform (shared timing) and per-segment displacement
    if cfg.respiration_variability:
        base_disp = resp.displacement(t)
    else:
        f = resp.rate_bpm / 60.0
        base_disp = (resp.amplitude_mm * 1e-3) * np.sin(2 * np.pi * f * t)

    segments = default_body(cfg.async_level) if cfg.extended_body else \
        [BodySegment(0, 0, 1.0, 0.0, 0.5)]

    # precompute per-segment displacement: phase offset = circular time shift
    samples_per_cycle = radio.sample_rate * 60.0 / max(resp.rate_bpm, 1e-6)
    seg_disp = []
    for seg in segments:
        shift = int(round(seg.phase / (2 * np.pi) * samples_per_cycle))
        seg_disp.append(seg.excursion * np.roll(base_disp, shift))

    # image sources (1st + 2nd order) for specular reflections
    x, y = tx.x, tx.y
    W, H = room.width, room.depth
    imgs = [([-x, y], 0.36), ([2*W-x, y], 0.36), ([x, -y], 0.30), ([x, 2*H-y], 0.30),
            ([-x, -y], 0.16), ([2*W-x, -y], 0.16), ([-x, 2*H-y], 0.14), ([2*W-x, 2*H-y], 0.14)]

    dD = _dist([tx.x, tx.y], [rx.x, rx.y])
    csi = np.zeros((nt, freqs.size), dtype=complex)

    # background micro-motion: a few slow-drifting phantom reflectors
    if cfg.background_motion:
        nb = 3
        bpos = [(rng.uniform(0.3, W-0.3), rng.uniform(0.3, H-0.3)) for _ in range(nb)]
        bfreq = rng.uniform(0.01, 0.08, nb)     # very slow (below breathing)
        bamp = cfg.background_level * rng.uniform(0.5, 1.5, nb)

    k2pi = 2 * np.pi
    for i in range(nt):
        h = np.zeros(freqs.size, dtype=complex)
        # direct
        a = 1.0 / (dD + 0.1)
        h += a * np.exp(-1j * k2pi * freqs * dD / C)
        # specular wall reflections
        for p, rc in imgs:
            d = _dist(p, [rx.x, rx.y]); a = rc / (d + 0.1)
            h += a * np.exp(-1j * k2pi * freqs * d / C)
        # person: sum over body segments (each with its own displacement)
        if present:
            for si, seg in enumerate(segments):
                sx, sy = body_xy[0] + seg.dx, body_xy[1] + seg.dy
                extra = 2.0 * seg_disp[si][i]          # round-trip path modulation
                dS = _dist([tx.x, tx.y], [sx, sy]) + _dist([sx, sy], [rx.x, rx.y]) + extra
                a = 0.5 * seg.xsec / (dS + 0.1)
                h += a * np.exp(-1j * k2pi * freqs * dS / C)
        # background micro-motion reflectors
        if cfg.background_motion:
            for (bx, by), bf, ba in zip(bpos, bfreq, bamp):
                drift = ba * np.sin(2*np.pi*bf*t[i])
                d = _dist([tx.x, tx.y], [bx, by]) + _dist([bx, by], [rx.x, rx.y]) + drift
                a = 0.15 / (d + 0.1)
                h += a * np.exp(-1j * k2pi * freqs * d / C)
        csi[i] = h

    # Rician diffuse component: split into specular + diffuse
    if cfg.diffuse:
        Klin = 10 ** (cfg.rician_k_db / 10.0)
        w_spec = np.sqrt(Klin / (Klin + 1))
        w_diff = np.sqrt(1.0 / (Klin + 1))
        # diffuse: temporally-correlated complex Gaussian (smooth over time)
        sig_pow = np.mean(np.abs(csi) ** 2)
        diff = (rng.normal(0, 1, csi.shape) + 1j * rng.normal(0, 1, csi.shape))
        # smooth along time to give it realistic coherence (not white)
        kern = np.ones(3) / 3
        diff = np.apply_along_axis(lambda c: np.convolve(c, kern, mode="same"), 0, diff)
        diff *= np.sqrt(sig_pow) / (np.sqrt(np.mean(np.abs(diff)**2)) + 1e-12)
        csi = w_spec * csi + w_diff * diff

    lbl = {"model": "realistic", "resp_rate_bpm": resp.rate_bpm,
           "realism": {"extended_body": cfg.extended_body, "async": cfg.async_level,
                       "resp_var": cfg.respiration_variability, "diffuse": cfg.diffuse,
                       "rician_k_db": cfg.rician_k_db, "background": cfg.background_motion}}
    if label:
        lbl.update(label)
    return CSIResult(csi=csi, t=t, freqs=freqs, label=lbl, config=radio)
