"""
test_pass.py — Posture-Aware Subcarrier Selection (PASS, C2) validation.

Locks in the primitives and the ablation orderings:
  * sensitive-subcarrier selection recovers a known breathing rate,
  * turn (posture-change) detection finds motion bursts,
  * posture fingerprints are separable and classify correctly,
  * the PASS tracker re-selects per posture and estimates a rate,
  * the experiment's key orderings hold: turns fully detected, turn-gating
    lowers rate error, and a 2nd antenna (MIMO) improves posture classification.

Run:  python -m pytest tests/test_pass.py -v
"""
from __future__ import annotations
import sys, os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from csi_synth import (
    Node, Person, RadioConfig, generate_csi, NoiseConfig, apply_noise,
    select_sensitive, estimate_rate_subs, fused_snr_eff, detect_transitions,
    posture_fingerprint, classify_posture, learn_posture_profiles, PASSTracker,
)
from csi_synth.geometry import Room

FS = 20.0
CFG = RadioConfig(n_subcarriers=64, sample_rate=FS)


def _window(dx=0.0, dy=0.0, rate=15.0, dur=24.0, snr=20.0, seed=0, antennas=None):
    """Amplitude window; with 2 antennas, per-antenna amplitude is concatenated (MIMO)."""
    room = Room(5, 4)
    tx = Node(0.6, 2.0)
    ants = antennas if antennas is not None else [(4.4, 2.0)]
    person = Person(2.5 + dx, 2.0 + dy, breathing={"rate_bpm": rate, "amplitude_mm": 5.0})
    cols = []
    for ax, ay in ants:
        res = generate_csi(room, tx, Node(ax, ay), person, duration=dur, config=CFG)
        res = apply_noise(res, NoiseConfig(snr_db=snr, cfo_hz=120, sfo_ppm=3, agc_std=0.02, seed=seed))
        cols.append(res.amplitude)
    return np.concatenate(cols, axis=1)


# AX211's 2 Rx antennas (⟂ offset) break the single-link mirror-symmetry that
# makes some postures indistinguishable — this is the realistic classification config.
MIMO = [(4.4, 1.97), (4.4, 2.03)]


def test_select_and_estimate_recovers_rate():
    """Selected subcarriers recover the set breathing rate within 1 BPM."""
    for rate in [12.0, 15.0, 18.0]:
        amp = _window(rate=rate, snr=20.0, seed=1)
        subs = select_sensitive(amp, k=6, fs=FS)
        assert len(subs) == 6
        est = estimate_rate_subs(amp, subs, fs=FS)
        assert abs(est - rate) < 1.0, f"rate {rate}: got {est:.2f}"


def test_fused_snr_sensitive_beats_random():
    """Sensitive subcarriers give a higher fused breathing SNR_eff than random ones."""
    amp = _window(rate=15.0, snr=12.0, seed=2)
    good = select_sensitive(amp, k=6, fs=FS)
    rng = np.random.default_rng(0)
    bad = rng.choice([k for k in range(64) if k not in set(good.tolist())], 6, replace=False)
    assert fused_snr_eff(amp, good, fs=FS) > fused_snr_eff(amp, bad, fs=FS)


def test_detect_transition_finds_motion_burst():
    """A synthetic motion burst in the middle is detected as one transition."""
    amp = _window(rate=15.0, snr=18.0, seed=3)
    T, N = amp.shape
    burst = slice(T // 2, T // 2 + int(1.5 * FS))
    amp = amp.copy()
    amp[burst] += 0.5 * np.abs(amp).mean() * np.sin(np.linspace(0, 6 * np.pi, burst.stop - burst.start))[:, None]
    ev = detect_transitions(amp, fs=FS)
    assert len(ev) >= 1
    assert any(burst.start - FS <= e["center"] <= burst.stop + FS for e in ev)


def test_fingerprint_classification():
    """MIMO fingerprints of the four sleep postures (incl. the left/right mirror pair)
    classify correctly — the 2nd antenna is what makes this possible."""
    labels = {"supine": (0.0, 0.0), "left": (-0.10, 0.24),
              "right": (0.10, -0.24), "prone": (0.02, 0.14)}
    calib = {k: [_window(dx=v[0], dy=v[1], snr=22.0, seed=10 + i, antennas=MIMO) for i in range(2)]
             for k, v in labels.items()}
    profiles = learn_posture_profiles(calib, k=6, fs=FS)
    centroids = {k: p.fingerprint for k, p in profiles.items()}
    for k, v in labels.items():
        fp = posture_fingerprint(_window(dx=v[0], dy=v[1], snr=20.0, seed=99, antennas=MIMO))
        assert classify_posture(fp, centroids) == k


def test_pass_tracker_estimates():
    """PASSTracker classifies a window and returns a plausible breathing rate."""
    labels = {"supine": (0.0, 0.0), "lateral": (-0.10, 0.24)}
    calib = {k: [_window(dx=v[0], dy=v[1], rate=15.0, snr=22.0, seed=20 + i, antennas=MIMO) for i in range(2)]
             for k, v in labels.items()}
    profiles = learn_posture_profiles(calib, k=6, fs=FS)
    tracker = PASSTracker(profiles=profiles, k=6, fs=FS)
    out = tracker.estimate(_window(dx=-0.10, dy=0.24, rate=15.0, snr=18.0, seed=77, antennas=MIMO))
    assert out["posture"] in labels
    assert abs(out["bpm"] - 15.0) < 1.5
    assert out["snr_eff"] > 1.0


def test_experiment_orderings():
    """End-to-end: turns detected, gating lowers error, MIMO improves classification."""
    import pass_analysis as A
    r = A.run_experiment(verbose=False, n_test=4)
    assert r["turn_recall"] >= 0.75                     # most/all turns detected
    assert r["gated_mae"] <= r["naive_mae"] + 1e-9      # gating never hurts, usually helps
    assert r["naive_max"] >= r["naive_mae"]             # turns produce large worst-case errors
    assert r["acc_2ant"] > r["acc_1ant"]                # 2nd antenna resolves posture ambiguity
    # the sensitivity ranking genuinely shifts across postures
    assert min(r["subcarrier_overlap"].values()) < 1.0


if __name__ == "__main__":
    test_select_and_estimate_recovers_rate()
    test_fused_snr_sensitive_beats_random()
    test_detect_transition_finds_motion_burst()
    test_fingerprint_classification()
    test_pass_tracker_estimates()
    test_experiment_orderings()
    print("PASS tests: OK")
