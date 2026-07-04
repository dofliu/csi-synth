"""
clinical_analysis.py — Why a naive "motion-stops" apnea detector is not enough.

Most simple CSI apnea detectors flag an event when respiratory MOTION drops.
This works for central apnea (effort ceases) but has two clinically critical
failure modes that this analysis quantifies:

  * Obstructive apnea (OSA): effort CONTINUES (the person strains against a
    blocked airway), so a motion-based detector sees strong movement and
    reports "normal" — MISSING the event entirely. OSA is the dominant
    phenotype, so this is a disqualifying failure for screening.

  * Hypopnea: only a partial (>=30%) reduction, so a threshold tuned for full
    apnea under-detects it, while a sensitive threshold false-alarms on normal
    respiratory variability.

The discriminating information for OSA is thoraco-abdominal PARADOX: thorax and
abdomen move in opposition. Because the twin places thorax and abdomen as
separate scatterers, the CSI carries this signature; we show that an
amplitude-only detector cannot use it, motivating a paradox-aware model.

Output: per-event-type detection sensitivity for a naive envelope detector,
and the mean respiratory-amplitude envelope per event type (showing OSA looks
like normal breathing to an amplitude detector). Reportable for the paper's
clinical-scenario section.

Honesty: parameters follow clinical definitions; the CSI mapping is a model
and absolute detectability must be validated on real annotated recordings.
"""
from __future__ import annotations
import sys, os
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from csi_synth.clinical import (SleepBreathingModel, ClinicalEvent, generate_clinical_csi,
                                NORMAL, HYPOPNEA, APNEA_OSA, APNEA_CSA, EVENT_NAMES)
from csi_synth.geometry import Room, Node
from csi_synth.generator import RadioConfig

FS = 20.0
NSUB = 64
ROOM, TX, RX, BED = Room(5.0, 4.0), Node(0.6, 2.0), Node(4.4, 2.0), (2.2, 1.6)


def respiratory_envelope(amp, win_s=5.0):
    """Sliding-window respiratory motion amplitude on the best subcarrier,
    band-passed to the respiratory band so out-of-band noise does not mask
    the amplitude collapse during apnea."""
    sm = np.apply_along_axis(lambda c: np.convolve(c, np.ones(5)/5, mode="same"), 0, amp)
    k = int(np.argmax(np.var(sm, axis=0)))
    x = sm[:, k].astype(float)
    # band-pass ~0.15-1.2 Hz: highpass (remove slow drift) then lowpass (remove noise)
    lp_long = int(FS*6);  lp_short = max(1, int(FS*0.3))
    hp = x - np.convolve(x, np.ones(lp_long)/lp_long, mode="same")
    bp = np.convolve(hp, np.ones(lp_short)/lp_short, mode="same")
    w = int(win_s*FS)
    env = np.array([bp[max(0, i-w):i+1].std() for i in range(len(bp))])
    return env


def build_night(seed):
    """Fixed event script so all seeds share ground truth."""
    ev = [ClinicalEvent(HYPOPNEA, 25, 12),
          ClinicalEvent(APNEA_CSA, 55, 14),
          ClinicalEvent(APNEA_OSA, 90, 15),
          ClinicalEvent(HYPOPNEA, 125, 11),
          ClinicalEvent(APNEA_OSA, 155, 13)]
    return ev


def analyze(n_seeds=5, snr_db=22.0):
    radio = RadioConfig(n_subcarriers=NSUB, sample_rate=FS)
    # accumulate envelope by event type, and naive-detector hits
    env_by_type = {NORMAL: [], HYPOPNEA: [], APNEA_OSA: [], APNEA_CSA: []}
    hits = {HYPOPNEA: 0, APNEA_OSA: 0, APNEA_CSA: 0}
    totals = {HYPOPNEA: 0, APNEA_OSA: 0, APNEA_CSA: 0}

    for s in range(n_seeds):
        m = SleepBreathingModel(rate_bpm=15, amplitude_mm=5.0, seed=100+s)
        ev = build_night(s)
        amp, mask, t = generate_clinical_csi(ROOM, TX, RX, BED, m, ev,
                                             duration=180.0, radio=radio, snr_db=snr_db, seed=200+s)
        env = respiratory_envelope(amp)
        # normal baseline = median envelope over normal samples
        base = np.median(env[mask == NORMAL])
        # naive detector: event if envelope drops below 50% of baseline (motion reduced)
        flagged = env < 0.5*base
        for code in (HYPOPNEA, APNEA_OSA, APNEA_CSA):
            for e in [ee for ee in ev if ee.kind == code]:
                i0, i1 = int(e.start*FS), int((e.start+e.duration)*FS)
                seg = flagged[i0:i1]
                totals[code] += 1
                # detected if it flags for >=50% of the event
                if seg.mean() >= 0.5:
                    hits[code] += 1
        for code in env_by_type:
            env_by_type[code].append(env[mask == code].mean())

    print("=" * 66)
    print(" Clinical-event detection with a naive motion-envelope detector")
    print(f" {n_seeds} nights, SNR {snr_db:.0f} dB")
    print("=" * 66)
    print(f"\n {'event type':<22}{'mean resp. envelope':>20}{'  (vs normal)':>14}")
    print(" " + "-"*58)
    norm = np.mean(env_by_type[NORMAL])
    for code in (NORMAL, HYPOPNEA, APNEA_OSA, APNEA_CSA):
        e = np.mean(env_by_type[code])
        print(f" {EVENT_NAMES[code]:<22}{e:>20.4f}{e/norm:>13.2f}x")
    print(f"\n {'event type':<22}{'naive detector sensitivity':>28}")
    print(" " + "-"*50)
    for code in (APNEA_CSA, HYPOPNEA, APNEA_OSA):
        sens = hits[code]/max(totals[code], 1)
        flag = "" if sens > 0.6 else ("   <-- MISSED" if sens < 0.25 else "   <-- under-detected")
        print(f" {EVENT_NAMES[code]:<22}{sens*100:>26.0f}%{flag}")
    print("\n Interpretation:")
    print("  * Central apnea: motion stops -> envelope collapses -> detected.")
    print("  * Obstructive apnea: effort CONTINUES (envelope ~ normal) -> a motion")
    print("    detector MISSES it. The discriminator is thoraco-abdominal paradox,")
    print("    which amplitude alone cannot capture -> motivates a paradox-aware model.")
    print("  * Hypopnea: only partial reduction -> under-detected by an apnea threshold.")
    return env_by_type, hits, totals


if __name__ == "__main__":
    analyze()
