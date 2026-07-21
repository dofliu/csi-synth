"""
analyze_first_batch.py — Reproduce the first-real-batch feedback figures.

Runs the project's OWN loaders/estimators (no assumptions) over the three real
ESP32 CSI captures sitting next to this script, and writes figs/fig1..fig4.

    cd csi_synth
    PYTHONPATH=. python real_data/first_batch_20260721/analyze_first_batch.py

Findings (see README.md for the full write-up):
  * measured sample rate ~6.1 Hz (NOT the 20 Hz default) — always measure it
  * 9-subcarrier null/guard band at 23–31 (ESP32-CSI-tool HT20)
  * synthetic-tuned motion detector correctly locates the real walking event
  * but flags 5.9–9.0% of the two empty-room files as motion → detection
    thresholds need per-site calibration (paper contribution C4)
  * none of these three files is a scored `normal-supine` capture, so no
    breathing-rate accuracy is claimed here
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

for p in ["/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
          "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]:
    if os.path.exists(p):
        fm.fontManager.addfont(p)
        plt.rcParams["font.family"] = [fm.FontProperties(fname=p).get_name()]
        break
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 120

# repo import
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))          # csi_synth/ pkg root
from csi_synth import load_real_csi
from csi_synth.pass_select import (motion_series, detect_transitions,
                                   select_sensitive, fused_snr_eff)

OUT = os.path.join(HERE, "figs")
os.makedirs(OUT, exist_ok=True)
FILES = [
    ("空房間 A\n(clean_room 02:05)", "CSI_clean_room_20260721_020546.csv", "empty"),
    ("空房間 B\n(clean_room 02:18)", "CSI_clean_room_20260721_021822_trimmed.csv", "empty"),
    ("有人房間\n(in_room 02:31·坐→走)", "CSI_in_room_20260721_023127.csv", "motion"),
]
recs = []
for label, fname, kind in FILES:
    res = load_real_csi(os.path.join(HERE, fname))
    recs.append(dict(label=label, kind=kind, res=res,
                     amp=res.amplitude, fs=res.config.sample_rate, t=res.t))

BLUE, RED, GREEN, AMBER, GRAY = "#2B6CB0", "#C0392B", "#2E7D5B", "#B8860B", "#5A6B7A"

# FIG 1 — heatmaps
fig, axes = plt.subplots(3, 1, figsize=(11, 9.5))
for ax, r in zip(axes, recs):
    amp, fs, dur = r["amp"], r["fs"], r["t"][-1]
    disp = amp.copy(); cm = disp.max(axis=0, keepdims=True); cm[cm == 0] = 1; disp /= cm
    ax.imshow(disp.T, aspect="auto", origin="lower", cmap="viridis",
              extent=[0, dur, 0, amp.shape[1]], vmin=0, vmax=1)
    ax.set_ylabel("子載波 index")
    ax.set_title(f"{r['label'].replace(chr(10),' ')}   |   {amp.shape[0]} frames · "
                 f"{dur:.0f}s · fs≈{fs:.2f}Hz · {amp.shape[1]} 子載波", fontsize=10, loc="left")
    ax.text(dur*0.995, 27, "← null/guard band (23–31)", ha="right", va="center",
            color="white", fontsize=8)
    for e in detect_transitions(amp, fs=fs):
        ax.axvspan(e["start"]/fs, e["end"]/fs, color=RED, alpha=0.18)
axes[-1].set_xlabel("時間 (秒)　　紅色遮罩＝偵測到的動作區間")
fig.suptitle("圖1　三份實測資料總覽：振幅熱圖（每子載波正規化）", fontsize=13, y=0.995)
fig.tight_layout(rect=[0, 0, 1, 0.98]); fig.savefig(f"{OUT}/fig1_overview.png", bbox_inches="tight"); plt.close(fig)

# FIG 2 — sample rate
fig, axes = plt.subplots(1, 3, figsize=(12, 3.6), sharey=True)
for ax, r in zip(axes, recs):
    dt = np.diff(r["t"]); dt = dt[dt > 0]; inst = 1.0/dt
    ax.hist(inst, bins=60, range=(0, 15), color=BLUE, alpha=0.8)
    med = np.median(inst)
    ax.axvline(med, color=RED, lw=2, label=f"中位數 {med:.2f} Hz")
    ax.axvline(20, color=GREEN, lw=1.6, ls="--", label="程式預設 20 Hz")
    ax.axvline(1.2, color=AMBER, ls=":", lw=1.4)
    ax.set_title(r["label"].replace(chr(10), " "), fontsize=9)
    ax.set_xlabel("瞬時封包率 (Hz)"); ax.legend(fontsize=7, loc="upper right")
axes[0].set_ylabel("封包數")
fig.suptitle("圖2　採樣率診斷：實測 ~6.1 Hz，遠低於預設 20 Hz（但仍高於呼吸 Nyquist 1.2 Hz）", fontsize=12)
fig.tight_layout(rect=[0, 0, 1, 0.95]); fig.savefig(f"{OUT}/fig2_sample_rate.png", bbox_inches="tight"); plt.close(fig)

# FIG 3 — motion timeline
fig, axes = plt.subplots(3, 1, figsize=(11, 7.5))
for ax, r in zip(axes, recs):
    amp, fs = r["amp"], r["fs"]
    m = motion_series(amp, fs=fs); tt = np.arange(m.size)/fs
    base = np.median(m); mad = np.median(np.abs(m-base))+1e-12; thr = base+5.0*1.4826*mad
    ax.plot(tt, m, color=GRAY, lw=0.6)
    ax.axhline(thr, color=RED, ls="--", lw=1.2, label="現行閾值 (median+5·MAD)")
    ev = detect_transitions(amp, fs=fs); frac = sum(e["end"]-e["start"] for e in ev)/m.size*100
    for e in ev:
        ax.axvspan(e["start"]/fs, e["end"]/fs, color=RED, alpha=0.16)
    tag = "[正確抓到走動]" if r["kind"] == "motion" else "[空房間仍有誤報]"
    ax.set_title(f"{r['label'].replace(chr(10),' ')}   —   標為動作：{frac:.1f}%   {tag}", fontsize=10, loc="left")
    ax.set_ylabel("動作量"); ax.legend(fontsize=7, loc="upper right"); ax.set_xlim(0, tt[-1])
axes[-1].set_xlabel("時間 (秒)")
fig.suptitle("圖3　動作偵測（合成資料調校的偵測器直接套用真實資料）", fontsize=13)
fig.tight_layout(rect=[0, 0, 1, 0.97]); fig.savefig(f"{OUT}/fig3_motion.png", bbox_inches="tight"); plt.close(fig)

# FIG 4 — calibration sweep + SNR
mults = np.linspace(3, 12, 25)
fig, (axA, axB) = plt.subplots(1, 2, figsize=(12, 4.4))
for r, c in zip(recs, [BLUE, "#3182CE", RED]):
    amp, fs = r["amp"], r["fs"]; m = motion_series(amp, fs=fs)
    base = np.median(m); mad = np.median(np.abs(m-base))+1e-12
    fracs = [(m > base+mm*1.4826*mad).mean()*100 for mm in mults]
    style = "-" if r["kind"] == "empty" else "--"
    axA.plot(mults, fracs, style, color=c, lw=2, label=r["label"].replace(chr(10), " "))
axA.axvline(5.0, color=GRAY, ls=":", lw=1.4, label="現行值 (5·MAD)")
axA.set_xlabel("偵測閾值 (× MAD)"); axA.set_ylabel("被標為動作的時間比例 (%)")
axA.set_title("A. 調高閾值→空房間誤報下降\n（校準 = 學到這個場域的雜訊層級）", fontsize=10)
axA.legend(fontsize=7); axA.grid(alpha=0.25)
labels, snrs, colors = [], [], []
for r in recs:
    amp, fs = r["amp"], r["fs"]; sel = select_sensitive(amp, k=8, fs=fs, band=(0.1, 0.6))
    snrs.append(fused_snr_eff(amp, sel, fs=fs, band=(0.1, 0.6)))
    labels.append(r["label"].replace(chr(10), "\n"))
    colors.append(GREEN if r["kind"] == "empty" else AMBER)
bars = axB.bar(range(len(snrs)), snrs, color=colors, alpha=0.85)
axB.axhline(1.0, color=GRAY, ls=":", lw=1.2)
axB.set_xticks(range(len(labels))); axB.set_xticklabels(labels, fontsize=8)
axB.set_ylabel("呼吸頻段 fused SNR_eff")
axB.set_title("B. 呼吸頻段 SNR：空房間都在雜訊層級 (~1.5–2)\n走動那份的 4.0 是動作洩漏，不是呼吸", fontsize=10)
for b, s in zip(bars, snrs):
    axB.text(b.get_x()+b.get_width()/2, s+0.05, f"{s:.2f}", ha="center", fontsize=9)
fig.suptitle("圖4　「空房間誤報能不能靠學習改善？」— 能：把閾值校準到本場域雜訊層級", fontsize=12)
fig.tight_layout(rect=[0, 0, 1, 0.94]); fig.savefig(f"{OUT}/fig4_calibration.png", bbox_inches="tight"); plt.close(fig)

print("wrote fig1..fig4 to", OUT)
for r in recs:
    amp, fs = r["amp"], r["fs"]
    ev = detect_transitions(amp, fs=fs); frac = sum(e["end"]-e["start"] for e in ev)/amp.shape[0]*100
    sel = select_sensitive(amp, k=8, fs=fs, band=(0.1, 0.6)); snr = fused_snr_eff(amp, sel, fs=fs, band=(0.1, 0.6))
    print(f"{r['label'].replace(chr(10),' '):32s} fs={fs:.2f}Hz motion={frac:4.1f}% fusedSNR={snr:.2f}")
