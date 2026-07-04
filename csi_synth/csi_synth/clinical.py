"""
clinical.py — Stage-2 clinical respiratory-event model for csi_synth.

Real sleep-disordered breathing is not just "breathing" vs. "breath-hold".
An honest screening twin must model the events that actually drive the
Apnea-Hypopnea Index (AHI) and that make detection clinically hard:

1. Hypopnea (the missing half of AHI).
   Not a full stop but a >=30% reduction in airflow/effort for >=10 s with an
   associated desaturation/arousal. On CSI this appears as a partial collapse
   of respiratory amplitude, NOT its disappearance — much harder to detect
   than a full apnea, and responsible for roughly half of all scored events.

2. Obstructive vs. central apnea (OSA vs. CSA).
   - CSA: central drive ceases; thoracic/abdominal effort STOPS -> the CSI
     respiratory signal genuinely vanishes.
   - OSA: the airway is blocked but effort CONTINUES and intensifies;
     thorax and abdomen move in OPPOSITION (paradoxical, thoraco-abdominal
     asynchrony). Airflow is zero but MOTION is present, often with a
     characteristic paradoxical signature — the opposite of a central event.
   A device that only looks for "motion stops" will miss every obstructive
   event, the dominant OSA phenotype. Distinguishing them is the crux.

3. Respiratory variability and its effect on false alarms.
   Normal breathing already varies cycle-to-cycle; a naive apnea detector
   that thresholds on amplitude drop will fire on deep-breath/normal
   variation. We model this so the false-alarm cost can be measured.

This module builds per-sample effort waveforms (thorax and abdomen separately,
since their relationship is the OSA/CSA discriminator) plus an event label
mask, which the realism generator turns into CSI.

Honesty: parameters follow clinical definitions (AHI thresholds, event
durations) but the CSI mapping is a model; absolute detectability must be
validated on real annotated recordings.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

# clinical event codes
NORMAL, HYPOPNEA, APNEA_OSA, APNEA_CSA = 0, 1, 2, 3
EVENT_NAMES = {NORMAL: "normal", HYPOPNEA: "hypopnea",
               APNEA_OSA: "obstructive apnea", APNEA_CSA: "central apnea"}


@dataclass
class ClinicalEvent:
    kind: int
    start: float          # seconds
    duration: float       # seconds (>=10 s for a scored event)


@dataclass
class SleepBreathingModel:
    rate_bpm: float = 15.0
    amplitude_mm: float = 5.0
    hypopnea_fraction: float = 0.4    # residual effort during hypopnea (0.3-0.5 typical)
    ie_ratio: float = 0.40
    period_cv: float = 0.08
    amp_cv: float = 0.10
    seed: int | None = None

    def _cycle_waveform(self, t, rng):
        """Base normalized effort in [-1, 1] with physiological asymmetry+variability."""
        f0 = self.rate_bpm / 60.0
        dt = t[1] - t[0] if len(t) > 1 else 1/20
        n = len(t)
        drift = rng.normal(0, self.period_cv, n).cumsum()
        win = int(1/f0/dt) or 1
        drift = np.convolve(drift, np.ones(win)/win, mode="same"); drift -= drift.mean()
        inst_f = f0 * (1 + np.clip(drift, -0.5, 0.5))
        phase = 2*np.pi*np.cumsum(inst_f)*dt
        cyc = (phase/(2*np.pi)) % 1.0
        r = self.ie_ratio
        d = np.where(cyc < r, 0.5*(1-np.cos(np.pi*cyc/r)),
                     0.5*(1+np.cos(np.pi*(cyc-r)/(1-r))))
        return (d-0.5)*2.0

    def effort_waveforms(self, duration, fs, events):
        """
        Returns (thorax_mm, abdomen_mm, label_mask) sampled at fs.
        thorax and abdomen are the two independent effort channels; their
        relationship encodes OSA (paradoxical) vs CSA (both stop).
        """
        rng = np.random.default_rng(self.seed)
        t = np.arange(int(round(duration*fs)))/fs
        base = self._cycle_waveform(t, rng)
        amp_mod = 1 + self.amp_cv*np.sin(2*np.pi*0.03*t + rng.uniform(0, 6.28))
        a = self.amplitude_mm

        # nominal: abdomen leads thorax slightly, same sign (synchronous)
        shift = int(0.4*fs)
        thorax = a*amp_mod*base
        abdomen = 0.85*a*amp_mod*np.roll(base, shift)
        gain = np.ones_like(t)          # amplitude envelope (events modulate this)
        paradox = np.zeros_like(t, dtype=bool)
        central = np.zeros_like(t, dtype=bool)
        mask = np.full(t.shape, NORMAL, dtype=int)

        for ev in events:
            i0 = int(ev.start*fs); i1 = int((ev.start+ev.duration)*fs)
            i1 = min(i1, len(t))
            if ev.kind == HYPOPNEA:
                gain[i0:i1] = self.hypopnea_fraction    # partial reduction
                mask[i0:i1] = HYPOPNEA
            elif ev.kind == APNEA_CSA:
                gain[i0:i1] = 0.0                        # effort stops entirely
                central[i0:i1] = True
                mask[i0:i1] = APNEA_CSA
            elif ev.kind == APNEA_OSA:
                # effort CONTINUES (often intensifies) but becomes paradoxical
                gain[i0:i1] = 1.15
                paradox[i0:i1] = True
                mask[i0:i1] = APNEA_OSA

        thorax = thorax*gain
        # abdomen: during OSA, paradoxical (opposite sign to thorax); during CSA, stops
        abd = abdomen*gain
        abd = np.where(paradox, -1.0*abd, abd)          # paradoxical inversion
        abd = np.where(central, 0.0, abd)
        thorax = np.where(central, 0.0, thorax)
        return thorax*1e-3, abd*1e-3, mask               # metres, metres, labels


def default_night(duration=180.0):
    """A short synthetic 'night' with a mix of events for testing."""
    return [
        ClinicalEvent(HYPOPNEA,  25, 12),
        ClinicalEvent(APNEA_OSA, 60, 15),
        ClinicalEvent(APNEA_CSA, 100, 14),
        ClinicalEvent(HYPOPNEA,  135, 11),
        ClinicalEvent(APNEA_OSA, 160, 13),
    ]


def ahi(events, hours):
    """Apnea-Hypopnea Index = scored events per hour."""
    scored = [e for e in events if e.duration >= 10 and e.kind in (HYPOPNEA, APNEA_OSA, APNEA_CSA)]
    return len(scored)/max(hours, 1e-9)


# ── clinical CSI generation (thorax + abdomen as two scattering centres) ──
def generate_clinical_csi(room, tx, rx, body_xy, model, events,
                          duration=180.0, radio=None, snr_db=22.0, seed=None):
    """
    Generate CSI for a night with clinical events. Thorax and abdomen are
    separate scatterers driven by the two effort channels, so the CSI carries
    the thoraco-abdominal relationship that discriminates OSA from CSA.
    Returns (amplitude[T,K], label_mask[T], t).
    """
    from .generator import RadioConfig, C
    import numpy as np
    radio = radio or RadioConfig()
    freqs = radio.subcarrier_freqs
    fs = radio.sample_rate
    th, abd, mask = model.effort_waveforms(duration, fs, events)
    n = len(th)
    t = np.arange(n)/fs
    rng = np.random.default_rng(seed)

    def dist(a, b):
        return np.hypot(a[0]-b[0], a[1]-b[1])
    x, y = tx.x, tx.y; W, H = room.width, room.depth
    imgs = [([-x, y], 0.36), ([2*W-x, y], 0.36), ([x, -y], 0.30), ([x, 2*H-y], 0.30)]
    dD = dist((tx.x, tx.y), (rx.x, rx.y))
    bx, by = body_xy
    # thorax slightly above abdomen in the bed
    thorax_xy = (bx, by-0.12); abd_xy = (bx, by+0.10)

    amp = np.zeros((n, freqs.size))
    k2pi = 2*np.pi
    for i in range(n):
        re = np.zeros(freqs.size); im = np.zeros(freqs.size)
        a = 1.0/(dD+0.1); ph = k2pi*freqs*dD/C; re += a*np.cos(ph); im -= a*np.sin(ph)
        for p, rc in imgs:
            d = dist(p, (rx.x, rx.y)); a = rc/(d+0.1); ph = k2pi*freqs*d/C
            re += a*np.cos(ph); im -= a*np.sin(ph)
        for (sx, sy), disp, xsec in [(thorax_xy, th[i], 0.55), (abd_xy, abd[i], 0.45)]:
            dS = dist((tx.x, tx.y), (sx, sy)) + dist((sx, sy), (rx.x, rx.y)) + 2.0*disp
            a = 0.5*xsec/(dS+0.1); ph = k2pi*freqs*dS/C
            re += a*np.cos(ph); im -= a*np.sin(ph)
        av = np.hypot(re, im)
        amp[i] = av
    # AWGN
    sp = np.mean(amp**2); sd = np.sqrt(sp/(10**(snr_db/10)))
    amp = np.abs(amp + rng.normal(0, sd, amp.shape)*1.1)
    return amp, mask, t
