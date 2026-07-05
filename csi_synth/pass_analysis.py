"""
pass_analysis.py — Posture-Aware Subcarrier Selection (PASS) ablation, thesis C2.

Research question (Ch.5 ablation, experiment E3):
    A sleeper turns over through the night. The set of breathing-sensitive
    subcarriers is posture-dependent (Fresnel sensitivity S_k shifts with the
    scatter geometry). Does DETECTING the turn and RE-SELECTING subcarriers for
    the new posture recover breathing accuracy that a fixed selection loses?

Design:
    One room, one low-SNR "night": supine → (turn) → left-lateral → (turn) →
    right-lateral → (turn) → prone → (turn) → supine, each posture a stable
    breathing segment, each turn a short motion burst that masks breathing.

    Three estimators, same data:
      (A) FIXED   — sensitive subcarriers chosen once (while supine), kept all night.
      (B) PASS    — detect each turn, classify the new posture from its channel
                    fingerprint, switch to that posture's learned subcarriers.
      (C) ORACLE  — per-segment best subcarriers from the test data (upper bound).

    Metrics: breathing-rate MAE (BPM) overall and per posture; fused SNR_eff;
    turn-detection recall; posture-classification accuracy.

Honesty: synthetic data validates the METHOD and the ordering FIXED < PASS ≤ ORACLE,
not absolute accuracy. Re-validate on real AX211 captures.
"""
from __future__ import annotations
import sys, os
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from csi_synth import Node, Person, RadioConfig, generate_csi, NoiseConfig, apply_noise
from csi_synth.geometry import Room, path_lengths
from csi_synth.generator import CSIResult, C
from csi_synth import pass_select as P

FS = 20.0
NSUB = 64
CFG = RadioConfig(n_subcarriers=NSUB, sample_rate=FS)
CAL_SNR = 22.0            # calibration windows are clean
TEST_SNR = 10.0          # low SNR at test → subcarrier choice becomes decisive
TOP_K = 6
SEG_S = 24.0             # seconds of stable breathing per posture
TURN_S = 1.6            # seconds of turning motion between postures
N_TEST = 24              # independent low-SNR test windows per posture

ROOM = dict(w=5.0, h=4.0, tx=(0.6, 2.0), rx=(4.4, 2.0), bed=(2.5, 2.0))
# AX211 has 2 Rx antennas. Offsetting the 2nd ⟂ to the Tx→Rx line breaks the
# single-link mirror-symmetry that makes left/right-lateral indistinguishable.
RX_ANTENNAS = [(4.4, 1.97), (4.4, 2.03)]
# Posture = chest (dx, dy) offset from bed centre. Tx→Rx line is horizontal (y=2.0),
# so the PERPENDICULAR (dy) offset is what most reshuffles subcarrier sensitivity.
# Lateral sleep shifts the thorax off the bed centreline by ~0.3 m — physically real
# and enough to move the breathing-sensitive subcarrier set substantially.
POSTURES = {
    "supine":        (0.00,  0.00),
    "left-lateral":  (-0.10,  0.24),
    "right-lateral": (0.10, -0.24),
    "prone":         (0.02,  0.14),
}
# posture -> breathing rate (BPM). Distinct rates so an estimate that locks onto
# a stale subcarrier set (wrong posture) shows up as rate error, not luck.
POSTURE_RATE = {"supine": 15.0, "left-lateral": 13.0, "right-lateral": 17.0, "prone": 12.0}
NIGHT = ["supine", "left-lateral", "right-lateral", "prone", "supine"]


def _room_nodes():
    return (Room(width=ROOM["w"], depth=ROOM["h"]),
            Node(*ROOM["tx"]), Node(*ROOM["rx"]), ROOM["bed"])


def gen_posture_window(posture, rate, dur, seed, snr, antennas=None):
    """
    One stable-posture breathing window at a given SNR → amplitude (T, N·A).
    With multiple Rx antennas, per-antenna amplitude is concatenated along the
    subcarrier axis (a stacked MIMO feature vector).
    """
    room, tx, _, (bx, by) = _room_nodes()
    ants = antennas if antennas is not None else [ROOM["rx"]]
    dx, dy = POSTURES[posture]
    person = Person(bx + dx, by + dy, breathing={"rate_bpm": rate, "amplitude_mm": 5.0})
    cols = []
    for ax, ay in ants:
        res = generate_csi(room, tx, Node(ax, ay), person, duration=dur, config=CFG)
        res = apply_noise(res, NoiseConfig(snr_db=snr, cfo_hz=120, sfo_ppm=3,
                                           agc_std=0.02, seed=seed))
        cols.append(res.amplitude)
    return np.concatenate(cols, axis=1)


def gen_posture_clean(posture, rate, dur, seed, antennas=None):
    """One clean (calibration-SNR) stable-posture window → amplitude (T, N·A)."""
    return gen_posture_window(posture, rate, dur, seed, CAL_SNR, antennas)


def _turn_csi(p_from, p_to, dur, rate):
    """
    A short 'turning over' transient: the chest sweeps from one posture position
    to the next while a large bulk motion dominates (breathing is masked). Built
    frame-by-frame so it produces a detectable motion burst.
    """
    room, tx, rx, (bx, by) = _room_nodes()
    n = int(round(dur * FS))
    t = np.arange(n) / FS
    fx, fy = POSTURES[p_from]
    gx, gy = POSTURES[p_to]
    freqs = CFG.subcarrier_freqs
    kph = -1j * 2 * np.pi / C
    csi = np.zeros((n, freqs.size), dtype=complex)
    # Turning over is a LARGE, fast whole-body movement — the torso scatterer swings
    # through a ~0.4 m arc, dwarfing the mm-scale breathing motion. Modelled as a
    # raised-cosine excursion perpendicular to the posture sweep.
    for i in range(n):
        frac = (i + 0.5) / n
        roll = 0.40 * np.sin(np.pi * frac)          # metres, transient bulk body motion
        px = bx + fx + (gx - fx) * frac + 0.18 * np.sin(np.pi * frac)
        py = by + fy + (gy - fy) * frac + roll
        person = Person(px, py, breathing={"rate_bpm": rate, "amplitude_mm": 5.0})
        disp = person.chest_displacement(np.array([t[i]]))[0]
        extra = 2.0 * disp
        h = np.zeros(freqs.size, dtype=complex)
        for length, amp, _ in path_lengths(tx, rx, person, room, extra_scatter=extra):
            h += amp * np.exp(kph * freqs * length)
        csi[i] = h
    return csi


def build_night(seed=100):
    """
    Assemble the multi-posture night as ONE CSIResult, then add test noise once
    (so the whole night shares a coherent impairment stream). Returns amplitude
    plus a ground-truth timeline.
    """
    room, tx, rx, (bx, by) = _room_nodes()
    parts, timeline = [], []      # timeline: per-frame dict rows built as (posture, rate, is_turn)
    frame0 = 0
    for i, posture in enumerate(NIGHT):
        rate = POSTURE_RATE[posture]
        dx, dy = POSTURES[posture]
        person = Person(bx + dx, by + dy, breathing={"rate_bpm": rate, "amplitude_mm": 5.0})
        seg = generate_csi(room, tx, rx, person, duration=SEG_S, config=CFG).csi
        parts.append(seg)
        timeline.append({"start": frame0, "end": frame0 + seg.shape[0],
                         "posture": posture, "rate": rate, "is_turn": False})
        frame0 += seg.shape[0]
        if i < len(NIGHT) - 1:
            turn = _turn_csi(posture, NIGHT[i + 1], TURN_S, rate)
            parts.append(turn)
            timeline.append({"start": frame0, "end": frame0 + turn.shape[0],
                             "posture": None, "rate": None, "is_turn": True})
            frame0 += turn.shape[0]

    csi = np.concatenate(parts, axis=0)
    t = np.arange(csi.shape[0]) / FS
    res = CSIResult(csi=csi, t=t, freqs=CFG.subcarrier_freqs,
                    label={"scenario": "pass-night"}, config=CFG)
    res = apply_noise(res, NoiseConfig(snr_db=TEST_SNR, cfo_hz=150, sfo_ppm=4,
                                       agc_std=0.03, seed=seed))
    return res.amplitude, timeline


def _true_posture_at(timeline, a, b):
    """The ground-truth stable posture/rate that best overlaps frames [a,b)."""
    best, best_ov = None, 0
    for row in timeline:
        if row["is_turn"]:
            continue
        ov = max(0, min(b, row["end"]) - max(a, row["start"]))
        if ov > best_ov:
            best_ov, best = ov, row
    return best


def _night_gating_eval(amp, timeline, turns, subs, win_s=12.0, hop_s=2.0,
                       tracker=None):
    """
    Slide a window across the night estimating breathing rate. Compare NAIVE
    (estimate every window, including motion-corrupted turn windows) vs PASS-GATED
    (suppress windows overlapping a detected turn). Also classify posture on the
    clean (non-turn) windows if a tracker is given. Returns error lists + counts.
    """
    W = int(round(win_s * FS))
    hop = int(round(hop_s * FS))
    det_centers = [e["center"] for e in turns]
    gate = int(round(0.5 * FS)) + W // 2

    def true_rate(c):
        for row in timeline:
            if not row["is_turn"] and row["start"] <= c < row["end"]:
                return row["rate"], row["posture"]
        return None, None

    naive, gated, n_gate, correct = [], [], 0, []
    for s in range(0, amp.shape[0] - W, hop):
        c = s + W // 2
        tr, posture = true_rate(c)
        est = P.estimate_rate_subs(amp[s:s + W], subs, fs=FS)
        gated_out = any(abs(c - dc) < gate for dc in det_centers)
        if tr is not None:                       # window sits in a stable posture
            naive.append(abs(est - tr))
            if gated_out:
                n_gate += 1
            else:
                gated.append(abs(est - tr))
                if tracker is not None:
                    correct.append(tracker.update(amp[s:s + W]) is not None
                                   and tracker.current_posture == posture)
        elif gated_out:                          # correctly suppressed a turn window
            n_gate += 1
    return dict(naive=naive, gated=gated, n_gate=n_gate, correct=correct)


def run_experiment(verbose=True, n_test=N_TEST):
    # ── 1) learn per-posture profiles (fingerprint + sensitive subcarriers) from CLEAN calib ──
    calib = {}
    for j, posture in enumerate(POSTURE_RATE):
        wins = [gen_posture_clean(posture, POSTURE_RATE[posture], 14.0, seed=500 + j * 10 + r)
                for r in range(3)]
        calib[posture] = wins
    profiles = P.learn_posture_profiles(calib, k=TOP_K, fs=FS)
    fixed_subs = profiles["supine"].subcarriers
    tracker = P.PASSTracker(profiles=profiles, k=TOP_K, fs=FS)

    # ── PREMISE: is the breathing-sensitive subcarrier set posture-dependent? ──
    supine_set = set(profiles["supine"].subcarriers.tolist())
    overlaps = {p: len(supine_set & set(profiles[p].subcarriers.tolist())) / TOP_K
                for p in POSTURE_RATE}
    keys = list(POSTURE_RATE)
    fp_sim = {a: {b: float(np.dot(profiles[a].fingerprint, profiles[b].fingerprint))
                  for b in keys} for a in keys}

    # ── build a realistic night (postures + turns) ──
    amp, timeline = build_night(seed=100)
    turns = P.detect_transitions(amp, fs=FS)
    true_turns = [r for r in timeline if r["is_turn"]]
    tol = int(round(1.2 * FS))
    matched = sum(1 for tr in true_turns
                  if any(tr["start"] - tol <= ev["center"] <= tr["end"] + tol for ev in turns))
    turn_recall = matched / max(1, len(true_turns))
    turn_fp = max(0, len(turns) - matched)

    # ── HEADLINE: turn gating — motion during a turn corrupts the rate; PASS suppresses it ──
    tracker.history.clear()
    g = _night_gating_eval(amp, timeline, turns, fixed_subs, tracker=tracker)
    naive_mae = float(np.mean(g["naive"])) if g["naive"] else float("nan")
    gated_mae = float(np.mean(g["gated"])) if g["gated"] else float("nan")
    naive_max = float(np.max(g["naive"])) if g["naive"] else float("nan")
    posture_acc = float(np.mean(g["correct"])) if g["correct"] else float("nan")

    # ── HONEST re-selection ablation: does per-posture top-K beat the stale supine set? ──
    per_posture = {}
    for j, posture in enumerate(POSTURE_RATE):
        rate = POSTURE_RATE[posture]
        sf, sp, so = [], [], []
        for r in range(n_test):
            win = gen_posture_window(posture, rate, SEG_S, seed=3000 + j * 100 + r, snr=TEST_SNR)
            sf.append(P.fused_snr_eff(win, fixed_subs, fs=FS))
            sp.append(P.fused_snr_eff(win, profiles[posture].subcarriers, fs=FS))
            so.append(P.fused_snr_eff(win, P.select_sensitive(win, TOP_K, FS), fs=FS))
        per_posture[posture] = dict(rate=rate, snr_fixed=float(np.mean(sf)),
                                    snr_pass=float(np.mean(sp)), snr_oracle=float(np.mean(so)))
    agg = lambda key: float(np.mean([per_posture[p][key] for p in POSTURE_RATE]))
    snr_fixed, snr_pass, snr_oracle = agg("snr_fixed"), agg("snr_pass"), agg("snr_oracle")

    # ── POSTURE CLASSIFICATION: 1 antenna vs 2 (AX211 MIMO) on independent windows ──
    # A single Tx–Rx link cannot separate postures that are mirror-symmetric about the
    # Tx→Rx axis (left/right-lateral) — a 2nd antenna breaks the symmetry.
    def _classify_acc(antennas):
        cal = {p: [gen_posture_clean(p, POSTURE_RATE[p], 14.0, seed=800 + j * 10 + rr, antennas=antennas)
                   for rr in range(3)] for j, p in enumerate(POSTURE_RATE)}
        pr = P.learn_posture_profiles(cal, k=TOP_K, fs=FS)
        trk = P.PASSTracker(profiles=pr, k=TOP_K, fs=FS)
        acc = []
        for j, p in enumerate(POSTURE_RATE):
            for rr in range(n_test):
                w = gen_posture_window(p, POSTURE_RATE[p], SEG_S, seed=4000 + j * 100 + rr,
                                       snr=TEST_SNR, antennas=antennas)
                trk.update(w); acc.append(trk.current_posture == p)
        return float(np.mean(acc))

    acc_1ant = _classify_acc([ROOM["rx"]])
    acc_2ant = _classify_acc(RX_ANTENNAS)

    result = dict(subcarrier_overlap=overlaps, fp_sim=fp_sim,
                  turn_recall=turn_recall, turn_fp=turn_fp,
                  n_turns_true=len(true_turns), n_turns_det=len(turns),
                  naive_mae=naive_mae, gated_mae=gated_mae, naive_max=naive_max,
                  n_gated=g["n_gate"], acc_1ant=acc_1ant, acc_2ant=acc_2ant,
                  snr_fixed=snr_fixed, snr_pass=snr_pass, snr_oracle=snr_oracle,
                  per_posture=per_posture, profiles=profiles, amp=amp, timeline=timeline,
                  turns=turns, n_test=n_test)
    if verbose:
        _print_report(result)
    return result


def _print_report(r):
    print("=" * 72)
    print(" Posture-Aware Subcarrier Selection (PASS) · csi_synth (contribution C2)")
    print(f" one room · night with turns @ {TEST_SNR:.0f} dB · top-{TOP_K} subcarriers")
    print("=" * 72)

    print("\n[1] PREMISE — are the breathing-sensitive subcarriers posture-dependent?")
    print("    Top-K overlap with the supine set (1.0 = identical):")
    for p, ov in r["subcarrier_overlap"].items():
        bar = "█" * int(round(ov * 10))
        print(f"       {p:<14} {ov*100:4.0f}% {bar:<10}")
    ks = list(r["fp_sim"])
    print("    Channel-fingerprint cosine similarity (off-diagonal ≪ 1 ⇒ separable postures):")
    print("       " + " ".join(f"{k[:5]:>6}" for k in ks))
    for a in ks:
        print(f"       {a[:6]:>6} " + " ".join(f"{r['fp_sim'][a][b]:>6.2f}" for b in ks))

    print("\n[2] COMPONENTS — turn detection & posture classification")
    print(f"    Turn detection    : {r['n_turns_det']}/{r['n_turns_true']} true turns "
          f"(recall {r['turn_recall']*100:.0f}%, {r['turn_fp']} false pos)")
    print(f"    Posture classify  : 1 antenna {r['acc_1ant']*100:>3.0f}%  →  "
          f"2 antennas (AX211 MIMO) {r['acc_2ant']*100:>3.0f}%")
    print("      one link can't separate left/right-lateral (mirror-symmetric about the")
    print("      Tx→Rx axis); AX211's 2nd antenna breaks the symmetry → posture becomes usable.")

    print("\n[3] HEADLINE — turn gating (motion during a turn corrupts the breathing rate)")
    print(f"    Naive (estimate through turns)   MAE {r['naive_mae']:.2f} BPM  "
          f"(worst {r['naive_max']:.1f} BPM during a turn)")
    print(f"    PASS-gated (turn windows held)   MAE {r['gated_mae']:.2f} BPM  "
          f"({r['n_gated']} windows suppressed)")
    print(f"    → gating cuts rate error ×{r['naive_mae']/max(r['gated_mae'],1e-6):.1f} and removes")
    print("      the large motion-driven errors that cause apnea false alarms.")

    print("\n[4] RE-SELECTION — does per-posture top-K beat the stale supine set? (honest)")
    print(f"    {'':<16}{'FIXED':>9}{'PASS':>9}{'ORACLE':>9}   fused breathing SNR_eff")
    for p in POSTURE_RATE:
        pp = r["per_posture"][p]
        print(f"    {p:<16}{pp['snr_fixed']:>9.2f}{pp['snr_pass']:>9.2f}{pp['snr_oracle']:>9.2f}")
    print(f"    {'mean':<16}{r['snr_fixed']:>9.2f}{r['snr_pass']:>9.2f}{r['snr_oracle']:>9.2f}"
          f"   (PASS +{100*(r['snr_pass']/max(r['snr_fixed'],1e-6)-1):.0f}% vs fixed)")
    print("    NOTE: the re-selection gain is SMALL here — a single Tx–Rx link modulates all")
    print("    subcarriers by the same scalar chest displacement, so every subcarrier carries")
    print("    breathing similarly (consistent with the high-dim finding: the win is DIVERSITY/")
    print("    fusion, not one best subcarrier). A larger re-selection payoff is expected where")
    print("    posture moves the body across a Fresnel null — to be validated on real MIMO AX211.")

    print("\nTakeaway: PASS's turn-detect → posture-classify → re-select loop is validated end-")
    print("to-end. Its strong, immediate benefit in the twin is TURN GATING (no false readings")
    print("during motion); subcarrier re-selection is modest in this idealized link and is the")
    print("part that most needs real-hardware confirmation. [synthetic — method & ordering only]")


if __name__ == "__main__":
    run_experiment()
