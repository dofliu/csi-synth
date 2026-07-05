"""Generate the dual-task model (C3) results figure."""
import sys, os, numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.font_manager as fm
_cjk = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
try:
    fm.fontManager.addfont(_cjk); plt.rcParams["font.family"] = fm.FontProperties(fname=_cjk).get_name()
except Exception:
    pass
plt.rcParams["axes.unicode_minus"] = False
sys.path.insert(0, os.path.dirname(__file__))
import dual_task_analysis as A
from csi_synth.clinical import EVENT_NAMES, NORMAL, HYPOPNEA, APNEA_OSA, APNEA_CSA

r = A.run_experiment(verbose=True)

INK, SLATE, LINEN, GRAY, RED, GREEN, AMBER = \
    "#18191C", "#5A6B7A", "#B8B0A4", "#8B8F95", "#8B2020", "#375623", "#C55A11"
PANEL = "#FBFBFA"
fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(15, 4.6),
                                    gridspec_kw={"width_ratios": [3, 2.4, 2.4]})
fig.patch.set_facecolor("#EEEDE9")
for ax in (ax1, ax2, ax3):
    ax.set_facecolor(PANEL)

# (a) per-class recall: dual-task vs motion-only  — the clinical headline
classes = [NORMAL, HYPOPNEA, APNEA_OSA, APNEA_CSA]
names = ["正常", "低通氣", "阻塞型\nOSA", "中樞型\nCSA"]
dual = [r["rec_dual"][c] * 100 for c in classes]
mot = [r["rec_motion"][c] * 100 for c in classes]
x = np.arange(len(classes)); w = 0.38
ax1.bar(x - w / 2, dual, w, label="雙任務模型", color=SLATE)
ax1.bar(x + w / 2, mot, w, label="動作型偵測", color=GRAY)
ax1.set_xticks(x); ax1.set_xticklabels(names)
ax1.set_ylabel("偵測率 recall (%)", fontsize=11, color=INK)
ax1.set_title("(a) 雙任務救回動作型偵測漏掉的事件", fontsize=12, color=INK)
ax1.set_ylim(0, 108); ax1.legend(fontsize=9, loc="upper right")
for i, (d, m) in enumerate(zip(dual, mot)):
    ax1.text(i - w / 2, d + 2, f"{d:.0f}", ha="center", fontsize=8, color=INK)
    ax1.text(i + w / 2, m + 2, f"{m:.0f}", ha="center", fontsize=8, color=RED if m < 20 else INK)

# (b) confusion matrix
cm = r["confusion"]
cmn = cm / cm.sum(1, keepdims=True).clip(min=1)
im = ax2.imshow(cmn, cmap="Blues", vmin=0, vmax=1)
ax2.set_xticks(range(4)); ax2.set_yticks(range(4))
short = ["正常", "低通", "OSA", "CSA"]
ax2.set_xticklabels(short); ax2.set_yticklabels(short)
ax2.set_xlabel("預測", fontsize=10, color=INK); ax2.set_ylabel("真實", fontsize=10, color=INK)
ax2.set_title(f"(b) 事件混淆矩陣 · 4類 {r['acc4']*100:.0f}%", fontsize=12, color=INK)
for i in range(4):
    for j in range(4):
        ax2.text(j, i, f"{cm[i,j]}", ha="center", va="center",
                 color="white" if cmn[i, j] > 0.5 else INK, fontsize=10)

# (c) rate regression: predicted vs true (breathing-present windows)
present = r["event_true"] != APNEA_CSA
yt, yp = r["rate_true"][present], r["rate_pred"][present]
ax3.scatter(yt, yp, s=16, color=SLATE, alpha=0.6, edgecolor="none")
lims = [10, 21]
ax3.plot(lims, lims, "--", color=INK, lw=1)
ax3.set_xlim(lims); ax3.set_ylim(lims)
ax3.set_xlabel("真實呼吸率 (BPM)", fontsize=10, color=INK)
ax3.set_ylabel("估計呼吸率 (BPM)", fontsize=10, color=INK)
ax3.set_title(f"(c) 呼吸率迴歸 · MAE {r['rate_mae']:.2f} BPM", fontsize=12, color=INK)

fig.suptitle("輕量雙任務模型 (C3)：呼吸率迴歸 ＋ 呼吸事件分類  ·  L = α·L_reg + β·L_cls",
             fontsize=13, color=INK, y=1.0)
plt.tight_layout(rect=[0, 0, 1, 0.96])
out = os.path.join(os.path.dirname(__file__), "dual_task_results.png")
plt.savefig(out, dpi=130, facecolor="#EEEDE9")
print(f"saved {out}")
