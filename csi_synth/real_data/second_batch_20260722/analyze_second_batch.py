"""
analyze_second_batch.py — New-bedroom batch (2026-07-22), the "high sample rate"
recordings. Reproduces figs/diag_bursty_sampling.png using only the project's
own loaders/estimators.

    cd csi_synth
    PYTHONPATH=. python real_data/second_batch_20260722/analyze_second_batch.py

The headline finding: the "111-125 Hz" these files report is a MEDIAN — the
capture is bursty/non-uniform (Δt std > mean, effective rate ~63 Hz). Fed to
estimate_rate as if uniform, every breathing peak collapses onto the 0.1 Hz band
edge (a fake 6 bpm). resample_uniform() first and the peaks move to a sane
14-19 bpm — but even then these breathe files do NOT clearly beat the empty-room
SNR baseline, unlike the earlier clean 6 Hz uniform captures. Uniform sampling
matters more than a high nominal rate. See README.md.
"""
import os, numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.font_manager as fm
for _p in ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
           "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
    if os.path.exists(_p):
        fm.fontManager.addfont(_p); plt.rcParams["font.family"] = [fm.FontProperties(fname=_p).get_name()]; break
plt.rcParams["axes.unicode_minus"] = False; plt.rcParams["figure.dpi"] = 120

import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
from csi_synth import load_real_csi, RadioConfig, CSIResult
from csi_synth.estimate import bandpass
from csi_synth.twin_import import resample_uniform
from csi_synth.pass_select import select_sensitive, fused_snr_eff

BLUE, RED, GREEN, AMBER, GRAY = "#2B6CB0", "#C0392B", "#2E7D5B", "#B8860B", "#5A6B7A"
FILES = [
    ("new_clean  17:00 (空)", "CSI_new_clean_room_20260722_170000.csv", "empty"),
    ("new_clean2 17:13 (空)", "CSI_new_clean_room_2_20260722_171353.csv", "empty"),
    ("breathe    17:26",      "CSI_breathe_20260722_172613.csv", "breathe"),
    ("breathe2   17:28",      "CSI_breathe_2_20260722_172808.csv", "breathe"),
]

def resampled_estimate(res, fsu=20.0, band=(0.1, 0.6)):
    ru = resample_uniform(res, fs=fsu)
    from csi_synth import estimate_rate
    est = estimate_rate(ru, band=band)
    sel = select_sensitive(ru.amplitude, k=8, fs=fsu, band=band)
    snr = fused_snr_eff(ru.amplitude, sel, fs=fsu, band=band)
    return est["bpm"], est["peak_hz"], snr, ru

rows = []
for name, fname, kind in FILES:
    res = load_real_csi(os.path.join(HERE, fname))
    st = {k: res.label.get(k) for k in ("sample_rate_median_hz", "sample_rate_effective_hz",
                                        "sampling_dt_cv", "sampling_bursty")}
    bpm, pk, snr, ru = resampled_estimate(res)
    rows.append((name, kind, res, st, bpm, snr, ru))
    print(f"{name:24s} median={st['sample_rate_median_hz']:.0f}Hz effective={st['sample_rate_effective_hz']:.0f}Hz "
          f"bursty={st['sampling_bursty']}  → resampled bpm={bpm:.1f} SNR={snr:.2f}")

# ── figure ──
fig, axes = plt.subplots(2, 2, figsize=(12, 7.6)); (a, b), (c, d) = axes
# A: dt burstiness of breathe2
res_b2 = rows[3][2]; dt = np.diff(res_b2.t) * 1000; dt = dt[dt > 0]
a.hist(dt, bins=80, range=(0, 60), color=BLUE, alpha=0.85)
a.axvline(np.median(dt), color=RED, lw=2, label=f"中位數 {np.median(dt):.1f}ms→{1000/np.median(dt):.0f}Hz")
a.axvline(np.mean(dt), color=GREEN, lw=2, ls="--", label=f"平均 {np.mean(dt):.1f}ms→有效 {1000/np.mean(dt):.0f}Hz")
a.set_xlabel("封包間隔 dt (ms)"); a.set_ylabel("次數")
a.set_title("A. 取樣是爆發式非均勻（std>mean）\n中位數看似高，實際有效率低很多", fontsize=10); a.legend(fontsize=8)
# B: raw-median-fs vs resampled bpm
labels = [r[0].split(" ")[0] for r in rows]
from csi_synth import estimate_rate
raw_bpm = [estimate_rate(r[2], band=(0.1, 0.6))["bpm"] for r in rows]
res_bpm = [r[4] for r in rows]
x = np.arange(4); w = 0.36
b.bar(x - w/2, raw_bpm, w, color=AMBER, label="直接用中位數fs (假峰@0.10Hz)")
b.bar(x + w/2, res_bpm, w, color=BLUE, label="重取樣均勻20Hz後")
b.set_xticks(x); b.set_xticklabels(labels, fontsize=8); b.set_ylabel("估計呼吸率 (bpm)")
b.set_title("B. 非均勻→假峰卡頻帶邊緣；重取樣後修正", fontsize=10); b.legend(fontsize=8)
# C: resampled spectra breathe vs empty
for r, col in [(rows[1], GRAY), (rows[2], GREEN), (rows[3], BLUE)]:
    ru = r[6]; x2 = ru.amplitude.mean(axis=1); x2 = bandpass(x2 - x2.mean(), 20.0, 0.08, 0.8)
    T = x2.size; n = np.arange(T); fr = np.arange(0.05, 0.8, 0.004)
    mag = np.array([np.hypot(np.sum(x2*np.cos(2*np.pi*f/20.0*n)), np.sum(x2*np.sin(2*np.pi*f/20.0*n)))/T for f in fr])
    c.plot(fr, mag/mag.max(), color=col, lw=1.5, label=r[0].split(" ")[0])
c.axvspan(0.1, 0.6, color=GREEN, alpha=0.07); c.set_xlim(0.05, 0.8)
c.set_xlabel("頻率 (Hz)"); c.set_ylabel("正規化功率")
c.set_title("C. 重取樣後頻譜：breathe 未明顯高過空房間", fontsize=10); c.legend(fontsize=8)
# D: SNR summary
d.axis("off")
snrtxt = "D. 重取樣後 fused SNR_eff\n\n" + "\n".join(
    f"  {r[0]:22s}: {r[5]:.2f}" for r in rows)
snrtxt += ("\n\n→ 四者都在 ~2，breathe 沒勝出。\n對比上一批 6Hz 均勻: breathe 2.3-3.3\nvs 空房 1.5-2（清楚勝出）。\n\n"
           "→ 均勻取樣比高採樣率更重要。")
d.text(0.0, 0.98, snrtxt, fontsize=9, va="top", ha="left", color="#222", linespacing=1.4)

fig.suptitle("新臥室環境（2026-07-22）：高採樣率其實是爆發式非均勻，需重取樣", fontsize=12.5, y=0.995)
fig.tight_layout(rect=[0, 0, 1, 0.96])
out = os.path.join(HERE, "figs", "diag_bursty_sampling.png")
fig.savefig(out, bbox_inches="tight"); print("wrote", out)
