"""
dual_task_analysis.py — Dual-task vital-sign model ablation (thesis C3, experiment E4).

Research question (Ch.5, E4):
    Can ONE lightweight model jointly (a) estimate breathing rate and (b) classify
    the respiratory event {normal, hypopnea, OSA, CSA} from a CSI window — and does
    the classification head recover the events a MOTION-ONLY detector misses
    (obstructive apnea and hypopnea, the clinically dominant, hardest events)?

Setup: labelled 24 s windows (12 s normal baseline → 12 s event) from the clinical
effort model, varied over rate / posture / SNR. A small NumPy dual-task model
(shared trunk → rate head + event head, combined objective) is trained and compared
against the naive "motion stops ⇒ apnea" detector.

Honesty: SYNTHETIC data — validates the method and the relative ordering
(dual-task ≫ motion-only on OSA/hypopnea; OSA remains the hardest class on a single
link because its thoraco-abdominal paradox needs phase / MIMO). Re-validate on real
annotated AX211 recordings. The thesis's <1M-param BiLSTM with a focal objective is
in dual_task_torch.py (for the RTX 4080); this NumPy model is the runnable baseline.
"""
from __future__ import annotations
import sys, os
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from csi_synth import dual_task as D
from csi_synth.clinical import EVENT_NAMES, NORMAL, HYPOPNEA, APNEA_OSA, APNEA_CSA


def _split(n, frac=0.7, seed=0):
    idx = np.random.default_rng(seed).permutation(n)
    k = int(frac * n)
    return idx[:k], idx[k:]


def run_experiment(per_class=110, seed=1, verbose=True):
    ds = D.make_dataset(per_class=per_class, seed=seed)
    X, yr, ye, mo = ds["X_feat"], ds["y_rate"], ds["y_event"], ds["motion_pred"]
    tr, te = _split(len(ye), 0.7, seed=0)

    model = D.DualTaskMLP(seed=0).fit(X[tr], yr[tr], ye[tr])
    rate_hat, ev_hat = model.predict(X[te])
    yte_r, yte_e, mo_te = yr[te], ye[te], mo[te]

    present = yte_e != APNEA_CSA                      # breathing exists (rate defined)
    rate_mae = float(np.mean(np.abs(rate_hat[present] - yte_r[present])))
    acc4 = float(np.mean(ev_hat == yte_e))
    acc_bin = float(np.mean((ev_hat != NORMAL) == (yte_e != NORMAL)))

    classes = [NORMAL, HYPOPNEA, APNEA_OSA, APNEA_CSA]
    rec_dual, rec_motion = {}, {}
    for c in classes:
        sel = yte_e == c
        if sel.sum() == 0:
            continue
        rec_dual[c] = float(np.mean(ev_hat[sel] == c))
        # motion-only predicts only {NORMAL, CSA}: correct = NORMAL for normal, else "an event"
        rec_motion[c] = float(np.mean(mo_te[sel] == NORMAL)) if c == NORMAL \
            else float(np.mean(mo_te[sel] != NORMAL))
    cm = np.zeros((4, 4), int)
    for t_, p_ in zip(yte_e, ev_hat):
        cm[t_, p_] += 1

    result = dict(rate_mae=rate_mae, acc4=acc4, acc_bin=acc_bin,
                  rec_dual=rec_dual, rec_motion=rec_motion, confusion=cm,
                  n_train=len(tr), n_test=len(te), per_class=per_class,
                  rate_pred=rate_hat, rate_true=yte_r, event_true=yte_e, event_pred=ev_hat)
    if verbose:
        _print_report(result)
    return result


def _print_report(r):
    print("=" * 70)
    print(" Dual-task vital-sign model (rate + event) · csi_synth (contribution C3)")
    print(f" 24 s windows · {r['n_train']} train / {r['n_test']} test · NumPy baseline")
    print("=" * 70)
    print(f"\nTask 1 — breathing-rate regression : MAE {r['rate_mae']:.2f} BPM "
          f"(windows with breathing)")
    print(f"Task 2 — event classification      : {r['acc4']*100:.0f}% (4-class) · "
          f"{r['acc_bin']*100:.0f}% (event vs normal)")

    print("\nPer-class recall — dual-task vs the naive motion-only detector:")
    print(f"   {'event':<18}{'dual-task':>10}{'motion-only':>13}")
    for c in [NORMAL, HYPOPNEA, APNEA_OSA, APNEA_CSA]:
        if c not in r["rec_dual"]:
            continue
        miss = ""
        if c in (HYPOPNEA, APNEA_OSA) and r["rec_motion"][c] < 0.2:
            miss = "  ← motion-only blind"
        print(f"   {EVENT_NAMES[c]:<18}{r['rec_dual'][c]*100:>9.0f}%"
              f"{r['rec_motion'][c]*100:>12.0f}%{miss}")

    print("\nConfusion matrix (rows = truth, cols = prediction):")
    hdr = "".join(f"{EVENT_NAMES[c][:5]:>7}" for c in range(4))
    print("            " + hdr)
    for c in range(4):
        print(f"   {EVENT_NAMES[c][:9]:>9} " + "".join(f"{r['confusion'][c][j]:>7}" for j in range(4)))

    print("\nTakeaway: one shared model estimates breathing rate AND flags respiratory")
    print("events, recovering the hypopnea and obstructive apnea that a motion-only")
    print("detector misses entirely. OSA stays the hardest class on a single link — its")
    print("thoraco-abdominal paradox needs phase / 2-antenna MIMO (ties to C2's finding).")
    print("[synthetic — method & ordering only; re-validate on real annotated AX211]")


if __name__ == "__main__":
    run_experiment()
