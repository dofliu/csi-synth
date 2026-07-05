"""
test_dual_task.py — Dual-task vital-sign model (C3) validation.

Covers the NumPy pipeline end-to-end plus a gradient check of the hand-written
backprop, and a torch-guarded check of the thesis BiLSTM (runs only where torch
is installed — e.g. the lab's RTX 4080 / a CI job with torch).

Run:  python -m pytest tests/test_dual_task.py -v
"""
from __future__ import annotations
import sys, os
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from csi_synth import dual_task as D
from csi_synth import make_dataset, window_features, motion_only_predict, DualTaskMLP
from csi_synth.clinical import NORMAL, HYPOPNEA, APNEA_OSA, APNEA_CSA


def test_dataset_shapes_and_balance():
    ds = make_dataset(per_class=8, seed=0)
    assert ds["X_feat"].shape == (32, len(D.FEATURE_NAMES))
    assert ds["X_seq"].ndim == 3 and ds["X_seq"].shape[0] == 32
    assert set(ds["y_event"]) == {NORMAL, HYPOPNEA, APNEA_OSA, APNEA_CSA}
    assert np.bincount(ds["y_event"]).tolist() == [8, 8, 8, 8]


def test_drop_ratio_separates_and_motion_blind():
    """drop_ratio orders normal>hypopnea>CSA; motion-only catches CSA, misses OSA."""
    def drop(cls):
        vals = []
        for i in range(6):
            amp, _ = D._one_window(cls, 15.0, D._POS[i % 4], snr=22.0, seed=100 + i)
            vals.append(window_features(amp)[D._DROP_IDX])
        return np.mean(vals)
    d_norm, d_hypo, d_csa = drop(NORMAL), drop(HYPOPNEA), drop(APNEA_CSA)
    assert d_norm > d_hypo > d_csa
    # motion-only: flags CSA, stays silent on OSA (effort continues)
    fa_csa, _ = D._one_window(APNEA_CSA, 15.0, D._POS[0], 22.0, seed=7)
    fa_osa, _ = D._one_window(APNEA_OSA, 15.0, D._POS[0], 22.0, seed=8)
    assert motion_only_predict(window_features(fa_csa)) == APNEA_CSA
    assert motion_only_predict(window_features(fa_osa)) == NORMAL


def test_mlp_gradient_check():
    """Numerically verify the hand-written backprop of DualTaskMLP."""
    rng = np.random.default_rng(0)
    X = rng.normal(size=(24, 6)); yr = rng.uniform(11, 20, 24)
    ye = rng.integers(0, 4, 24)
    m = DualTaskMLP(hidden=8, seed=1)
    m._mu, m._sd = X.mean(0), X.std(0) + 1e-9
    m._rmu, m._rsd = float(yr.mean()), float(yr.std() + 1e-9)
    counts = np.bincount(ye, minlength=4).astype(float)
    m.class_w = counts.sum() / (4 * (counts + 1e-9))
    m._init(6)
    Xs = (X - m._mu) / m._sd; yrs = (yr - m._rmu) / m._rsd
    _, g = m._backward(Xs, yrs, ye)
    eps = 1e-5
    for name in ["W1", "Wc", "Wr"]:
        W = getattr(m, name)
        gi, gj = 0, 0
        W[gi, gj] += eps; lp, _ = m._backward(Xs, yrs, ye)
        W[gi, gj] -= 2 * eps; lm, _ = m._backward(Xs, yrs, ye)
        W[gi, gj] += eps
        num = (lp - lm) / (2 * eps)
        assert abs(num - g[name][gi, gj]) < 1e-4, f"{name}: num {num} vs analytic {g[name][gi,gj]}"


def test_mlp_learns_and_beats_chance():
    ds = make_dataset(per_class=40, seed=2)
    idx = np.random.default_rng(0).permutation(len(ds["y_event"]))
    k = int(0.7 * len(idx)); tr, te = idx[:k], idx[k:]
    m = DualTaskMLP(seed=0).fit(ds["X_feat"][tr], ds["y_rate"][tr], ds["y_event"][tr])
    rate_hat, ev_hat = m.predict(ds["X_feat"][te])
    yr, ye = ds["y_rate"][te], ds["y_event"][te]
    present = ye != APNEA_CSA
    assert np.mean(np.abs(rate_hat[present] - yr[present])) < 2.5     # rate MAE
    assert np.mean(ev_hat == ye) > 0.45                              # ≫ 25% chance
    # binary event-vs-normal is the clinically primary output
    assert np.mean((ev_hat != NORMAL) == (ye != NORMAL)) > 0.75


def test_experiment_clinical_ordering():
    """Dual-task recovers hypopnea/OSA that the motion-only detector misses."""
    import dual_task_analysis as A
    r = A.run_experiment(per_class=60, verbose=False)
    assert r["rate_mae"] < 2.5
    assert r["acc_bin"] > 0.8
    # motion-only is blind to hypopnea and OSA; dual-task is clearly better on both
    for c in (HYPOPNEA, APNEA_OSA):
        assert r["rec_motion"][c] < 0.25
        assert r["rec_dual"][c] > r["rec_motion"][c] + 0.3


def test_torch_bilstm_under_budget():
    """The thesis BiLSTM builds, stays <1M params, and takes a training step."""
    torch = pytest.importorskip("torch")
    import dual_task_torch as T
    model = T.DualTaskBiLSTM(input_dim=16)
    assert T.count_params(model) < 1_000_000
    x = torch.randn(4, 80, 16)
    rate, logits = model(x)
    assert rate.shape == (4,) and logits.shape == (4, 4)
    yr = torch.tensor([15., 13., 17., 12.]); ye = torch.tensor([0, 1, 2, 3])
    loss, _, _ = T.dual_task_loss(rate, logits, yr, ye)
    loss.backward()
    assert torch.isfinite(loss)


if __name__ == "__main__":
    test_dataset_shapes_and_balance()
    test_drop_ratio_separates_and_motion_blind()
    test_mlp_gradient_check()
    test_mlp_learns_and_beats_chance()
    test_experiment_clinical_ordering()
    print("dual-task tests: OK (torch test runs under pytest where torch is present)")
