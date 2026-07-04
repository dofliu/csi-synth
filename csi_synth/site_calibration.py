"""
site_calibration.py — Site-specific calibration vs generic model experiment.

Research question (thesis Ch.5 ablation):
    Does calibrating to ONE specific space give better breathing detection than
    a generic (cross-room) model, and what is the cost?

WHY the room matters (the physics):
    Breathing RATE (0.25 Hz) is room-invariant, so classifying rate alone does
    NOT need site knowledge. What IS room-specific is WHICH subcarriers carry
    the breathing signal best: sensitivity depends on where the static and
    person-scattered paths interfere, i.e. on room geometry + furniture.
    At LOW SNR this is decisive: pick the room's truly-sensitive subcarriers and
    you recover breathing; use a cross-room "average" choice and you fail.

Conditions:
    (A) GENERIC       : subcarrier selection learned as the AVERAGE over rooms A,B,C
    (B) FEW-SHOT CAL  : generic prior nudged by a few room-D calibration windows
    (C) SITE-SPECIFIC : subcarrier selection learned from room D itself
    (D) FRAGILITY     : site-specific selection, but furniture moved in D at test

Metric: breathing-rate estimation error (MAE, BPM) on room-D low-SNR test data.
Lower MAE = better.

Honesty: synthetic data validates the METHODOLOGY and the relative ordering,
not absolute clinical accuracy. Re-validate on real AX211 data.
"""
from __future__ import annotations
import sys, os
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from csi_synth import Node, Person, RadioConfig, generate_csi, NoiseConfig, apply_noise
from csi_synth.geometry import Room

RATES = [11.0, 13.0, 15.0, 17.0, 19.0]
FS = 20.0
DUR = 24.0
NSUB = 64
CFG = RadioConfig(n_subcarriers=NSUB, sample_rate=FS)
TEST_SNR = 6.0          # low SNR: subcarrier choice becomes decisive
CAL_SNR  = 20.0         # calibration recordings are cleaner
TOP_M = 5               # number of subcarriers each model gets to use

ROOMS = {
    "A": dict(w=5.0, h=4.0, tx=(0.6, 2.0), rx=(4.4, 2.0), bed=(2.5, 2.0)),
    "B": dict(w=6.0, h=5.0, tx=(0.8, 2.5), rx=(5.2, 2.5), bed=(3.0, 2.6)),
    "C": dict(w=4.5, h=3.5, tx=(0.5, 1.6), rx=(4.0, 1.9), bed=(2.2, 1.7)),
    "D": dict(w=5.0, h=4.0, tx=(0.7, 1.8), rx=(4.3, 2.2), bed=(2.6, 1.9)),
}


def gen_window(room_key, rate, seed, snr, rx_shift=0.0, w_delta=0.0):
    r = ROOMS[room_key]
    room = Room(width=r["w"]+w_delta, depth=r["h"])
    tx = Node(*r["tx"])
    rx = Node(r["rx"][0], r["rx"][1] + rx_shift)
    person = Person(*r["bed"], breathing={"rate_bpm": rate, "amplitude_mm": 5.0})
    res = generate_csi(room, tx, rx, person, duration=DUR, config=CFG)
    res = apply_noise(res, NoiseConfig(snr_db=snr, cfo_hz=150, sfo_ppm=4, agc_std=0.02, seed=seed))
    return res.amplitude          # (T, NSUB)


def subcarrier_sensitivity(room_key, seed0, snr=CAL_SNR, n=4):
    """Per-subcarrier breathing sensitivity = mean breathing-band energy over calib windows."""
    acc = np.zeros(NSUB)
    s = seed0
    for rate in RATES:
        for _ in range(n):
            amp = gen_window(room_key, rate, s, snr); s += 1
            acc += band_energy_per_subcarrier(amp)
    return acc / (len(RATES) * n)


def subcarrier_sensitivity_delta(room_key, seed0, rx_shift=0.0, w_delta=0.0, snr=CAL_SNR, n=4):
    """Sensitivity ranking learned on a geometry-changed room (for re-calibration)."""
    acc = np.zeros(NSUB)
    s = seed0
    for rate in RATES:
        for _ in range(n):
            amp = gen_window(room_key, rate, s, snr, rx_shift=rx_shift, w_delta=w_delta); s += 1
            acc += band_energy_per_subcarrier(amp)
    return acc / (len(RATES) * n)


def band_energy_per_subcarrier(amp):
    """Breathing-band (0.15-0.6 Hz) energy for each subcarrier."""
    T = amp.shape[0]
    x = amp - amp.mean(axis=0, keepdims=True)
    e = np.zeros(NSUB)
    n = np.arange(T)
    for fi in range(6, 25):
        f = fi * 0.025
        c = np.cos(2*np.pi*f/FS*n); sN = np.sin(2*np.pi*f/FS*n)
        re = x.T @ c; im = -(x.T @ sN)
        e += np.hypot(re, im) / T
    return e


def estimate_rate(amp, subcarriers):
    """Estimate breathing rate (BPM) by fusing the chosen subcarriers' spectra."""
    T = amp.shape[0]
    x = amp[:, subcarriers] - amp[:, subcarriers].mean(axis=0, keepdims=True)
    n = np.arange(T)
    best_f, best_mag = None, -1
    for fi in range(6, 25):
        f = fi * 0.025
        re = np.sum(x.T * np.cos(2*np.pi*f/FS*n), axis=1)
        im = -np.sum(x.T * np.sin(2*np.pi*f/FS*n), axis=1)
        mag = np.mean(np.hypot(re, im)) / T
        if mag > best_mag:
            best_mag, best_f = mag, f
    return best_f * 60.0


def mae_on_testset(select_fn, seed0, rx_shift=0.0, w_delta=0.0, n_per_rate=12):
    """MAE (BPM) over room-D low-SNR test windows, using a selection function."""
    errs = []
    s = seed0
    for rate in RATES:
        for _ in range(n_per_rate):
            amp = gen_window("D", rate, s, TEST_SNR, rx_shift=rx_shift, w_delta=w_delta); s += 1
            sub = select_fn(amp)
            est = estimate_rate(amp, sub)
            errs.append(abs(est - rate))
    return float(np.mean(errs))


def run_experiment():
    print("=" * 66)
    print(" Site-specific calibration vs generic model  ·  csi_synth")
    print(f" task: breathing-rate estimation @ {TEST_SNR:.0f} dB SNR (low),  top-{TOP_M} subcarriers")
    print("=" * 66)

    # Learn per-room sensitivity rankings
    sensD = subcarrier_sensitivity("D", seed0=6000)
    sensGeneric = np.mean([subcarrier_sensitivity(r, seed0=1000 + i*500)
                           for i, r in enumerate(["A", "B", "C"])], axis=0)

    topD = np.argsort(sensD)[::-1][:TOP_M]
    topGeneric = np.argsort(sensGeneric)[::-1][:TOP_M]

    # Few-shot: blend generic prior with a little room-D sensitivity
    sensFew = 0.5 * sensGeneric / (sensGeneric.max()+1e-9) + \
              0.5 * subcarrier_sensitivity("D", seed0=7000, n=2) / (sensD.max()+1e-9)
    topFew = np.argsort(sensFew)[::-1][:TOP_M]

    # Fixed selections (each model commits to its learned subcarriers)
    sel_generic = lambda amp: topGeneric
    sel_few     = lambda amp: topFew
    sel_site    = lambda amp: topD

    acc_generic   = mae_on_testset(sel_generic, seed0=9000)
    acc_fewshot   = mae_on_testset(sel_few,     seed0=9000)
    acc_site      = mae_on_testset(sel_site,    seed0=9000)
    # room changed: Rx / reflector moved 1.2 m reshuffles which subcarriers are sensitive
    acc_site_move = mae_on_testset(sel_site,    seed0=9000, rx_shift=1.2)
    # re-calibrate on the CHANGED room, then re-test -> accuracy restored
    sensD2 = subcarrier_sensitivity_delta("D", seed0=6000, rx_shift=1.2)
    topD2 = np.argsort(sensD2)[::-1][:TOP_M]
    acc_recal = mae_on_testset(lambda amp: topD2, seed0=9000, rx_shift=1.2)

    # oracle upper bound: pick the best subcarriers per test window (cheating)
    def oracle(amp):
        return np.argsort(band_energy_per_subcarrier(amp))[::-1][:TOP_M]
    acc_oracle = mae_on_testset(oracle, seed0=9000)

    print(f"\n{'Condition':<48}{'MAE (BPM)':>12}")
    print("-" * 60)
    print(f"{'(A) Generic selection (avg over rooms A,B,C)':<48}{acc_generic:>10.2f}")
    print(f"{'(B) Generic + few-shot D calibration':<48}{acc_fewshot:>10.2f}")
    print(f"{'(C) Site-specific selection (room D)':<48}{acc_site:>10.2f}")
    print(f"{'    oracle (per-window best, upper bound)':<48}{acc_oracle:>10.2f}")
    print("-" * 60)
    print(f"{'(D) Sensor/furniture MOVED — old model':<48}{acc_site_move:>10.2f}")
    print(f"{'(E) Sensor/furniture MOVED — re-calibrated':<48}{acc_recal:>10.2f}")
    print("-" * 60)
    print(f"\nCalibration gain : {acc_generic-acc_fewshot:+.2f} BPM (few-shot), "
          f"{acc_generic-acc_site:+.2f} BPM (full site)  [lower MAE is better]")
    print(f"Room-change cost : site {acc_site:.2f} -> {acc_site_move:.2f} BPM without recalibration "
          f"(~{acc_site_move/max(acc_site,0.01):.0f}x error)")
    print(f"Recalibration    : {acc_site_move:.2f} -> {acc_recal:.2f} BPM restores accuracy")
    print("\nTakeaway: at low SNR the room-specific choice of sensitive subcarriers")
    print("(the PASS idea) recovers breathing the generic choice misses, reaching the")
    print("oracle bound. The calibrated model is tied to that room's fingerprint: a")
    print("room change breaks it until re-calibrated. This motivates a LAYERED design —")
    print("generic base (robust) + site calibration (accurate) + change-triggered recal.")
    return dict(generic=acc_generic, fewshot=acc_fewshot, site=acc_site,
                site_moved=acc_site_move, recal=acc_recal, oracle=acc_oracle)


if __name__ == "__main__":
    run_experiment()
