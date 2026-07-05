"""
dual_task_torch.py — Thesis C3 model: a <1M-parameter dual-task BiLSTM.

Jointly, from a CSI window (T frames x C subcarriers):
    * regresses the breathing rate (BPM), and
    * classifies the respiratory event {normal, hypopnea, OSA, CSA},
trained with the combined objective  L = α·L_reg + β·L_cls, where L_reg is a
SmoothL1 on the rate and L_cls is a FOCAL loss (down-weights easy examples so the
minority event classes — the ones that matter — are learned).

This is the reference implementation for the lab's PyTorch + RTX 4080 setup. The
input sequences and labels come from csi_synth.dual_task.make_dataset() (the same
synthetic clinical windows the NumPy baseline in dual_task_analysis.py uses), so
the two are directly comparable. PyTorch is intentionally NOT a hard dependency of
the csi_synth package — import this module only where torch is installed.

Run (where torch is available):
    python dual_task_torch.py
Honesty: SYNTHETIC training — validates architecture and relative behaviour; the
final model must be trained and validated on real annotated AX211 recordings.
"""
from __future__ import annotations
import sys, os
import numpy as np

import torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, os.path.dirname(__file__))
from csi_synth import dual_task as D
from csi_synth.clinical import NORMAL, HYPOPNEA, APNEA_OSA, APNEA_CSA

N_CLASS = 4


class DualTaskBiLSTM(nn.Module):
    """
    Shared BiLSTM trunk → (rate head, event head). ~0.33M params at the defaults
    (input_dim=16, hidden=96, 2 layers, bidirectional) — well under the 1M budget.
    """
    def __init__(self, input_dim=16, hidden=96, layers=2, n_class=N_CLASS, dropout=0.2):
        super().__init__()
        self.lstm = nn.LSTM(input_dim, hidden, num_layers=layers, batch_first=True,
                            bidirectional=True, dropout=dropout if layers > 1 else 0.0)
        feat = 2 * hidden
        self.trunk = nn.Sequential(nn.Linear(feat, hidden), nn.ReLU(), nn.Dropout(dropout))
        self.rate_head = nn.Linear(hidden, 1)          # breathing-rate regression
        self.event_head = nn.Linear(hidden, n_class)   # event classification

    def forward(self, x):                              # x: (B, T, C)
        out, _ = self.lstm(x)
        pooled = out.mean(dim=1)                       # temporal average pooling
        h = self.trunk(pooled)
        return self.rate_head(h).squeeze(-1), self.event_head(h)


def count_params(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def focal_loss(logits, target, gamma=2.0, weight=None):
    """Multiclass focal loss: -(1-p_t)^gamma * log p_t, optional class weights."""
    logp = F.log_softmax(logits, dim=1)
    logp_t = logp.gather(1, target[:, None]).squeeze(1)
    p_t = logp_t.exp()
    loss = -((1 - p_t) ** gamma) * logp_t
    if weight is not None:
        loss = loss * weight[target]
    return loss.mean()


def dual_task_loss(rate_pred, event_logits, rate_true, event_true,
                   alpha=1.0, beta=1.0, class_weight=None, rate_mean=0.0, rate_std=1.0):
    """L = α·SmoothL1(rate) + β·Focal(event). Rate is standardized for the reg term."""
    rt = (rate_true - rate_mean) / rate_std
    l_reg = F.smooth_l1_loss((rate_pred - rate_mean) / rate_std, rt)
    l_cls = focal_loss(event_logits, event_true, weight=class_weight)
    return alpha * l_reg + beta * l_cls, l_reg.item(), l_cls.item()


def train(model, Xtr, yr_tr, ye_tr, Xva, yr_va, ye_va, epochs=60, lr=2e-3,
          alpha=1.0, beta=1.0, batch=64, device="cpu", verbose=True):
    """Train the dual-task model; returns a dict of validation metrics."""
    model.to(device)
    rate_mean, rate_std = float(yr_tr.mean()), float(yr_tr.std() + 1e-9)
    counts = np.bincount(ye_tr, minlength=N_CLASS).astype(float)
    cw = torch.tensor(counts.sum() / (N_CLASS * (counts + 1e-9)), dtype=torch.float32, device=device)

    Xtr_t = torch.tensor(Xtr, dtype=torch.float32, device=device)
    yr_t = torch.tensor(yr_tr, dtype=torch.float32, device=device)
    ye_t = torch.tensor(ye_tr, dtype=torch.long, device=device)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    n = len(Xtr)
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(n, device=device)
        for i in range(0, n, batch):
            idx = perm[i:i + batch]
            rate_p, ev_p = model(Xtr_t[idx])
            loss, _, _ = dual_task_loss(rate_p, ev_p, yr_t[idx], ye_t[idx],
                                        alpha, beta, cw, rate_mean, rate_std)
            opt.zero_grad(); loss.backward(); opt.step()
    return evaluate(model, Xva, yr_va, ye_va, device, verbose)


@torch.no_grad()
def evaluate(model, X, yr, ye, device="cpu", verbose=True):
    model.eval()
    Xt = torch.tensor(X, dtype=torch.float32, device=device)
    rate_p, ev_p = model(Xt)
    rate_p = rate_p.cpu().numpy()
    ev_hat = ev_p.argmax(1).cpu().numpy()
    present = ye != APNEA_CSA
    rate_mae = float(np.mean(np.abs(rate_p[present] - yr[present])))
    acc4 = float(np.mean(ev_hat == ye))
    acc_bin = float(np.mean((ev_hat != NORMAL) == (ye != NORMAL)))
    if verbose:
        print(f"[BiLSTM] params={count_params(model):,}  "
              f"rate MAE={rate_mae:.2f} BPM  4-class={acc4*100:.0f}%  binary={acc_bin*100:.0f}%")
    return dict(rate_mae=rate_mae, acc4=acc4, acc_bin=acc_bin, params=count_params(model))


def main(per_class=110, seed=1):
    ds = D.make_dataset(per_class=per_class, seed=seed)
    X, yr, ye = ds["X_seq"].astype(np.float32), ds["y_rate"], ds["y_event"]
    # standardize per-feature across the sequence dataset
    mu, sd = X.mean((0, 1), keepdims=True), X.std((0, 1), keepdims=True) + 1e-9
    X = (X - mu) / sd
    idx = np.random.default_rng(0).permutation(len(ye)); k = int(0.7 * len(idx))
    tr, va = idx[:k], idx[k:]
    model = DualTaskBiLSTM(input_dim=X.shape[2])
    assert count_params(model) < 1_000_000, "model exceeds the 1M-parameter budget"
    print(f"DualTaskBiLSTM parameters: {count_params(model):,} (<1M budget)")
    train(model, X[tr], yr[tr], ye[tr], X[va], yr[va], ye[va])
    print("[synthetic — re-validate on real annotated AX211 recordings]")


if __name__ == "__main__":
    main()
