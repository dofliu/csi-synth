"""Generate the PASS (posture-aware subcarrier selection, C2) results figure."""
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
import pass_analysis as A

r = A.run_experiment(verbose=True)

INK, SLATE, LINEN, GRAY, RED, GREEN, AMBER = \
    "#18191C", "#5A6B7A", "#B8B0A4", "#8B8F95", "#8B2020", "#375623", "#C55A11"
PANEL = "#FBFBFA"
fig, axs = plt.subplots(2, 2, figsize=(13, 9))
fig.patch.set_facecolor("#EEEDE9")
(ax1, ax2), (ax3, ax4) = axs
for ax in (ax1, ax2, ax3, ax4):
    ax.set_facecolor(PANEL)

# (a) subcarrier-set overlap with supine — sensitivity is posture-dependent
post = list(A.POSTURE_RATE)
ov = [r["subcarrier_overlap"][p] * 100 for p in post]
b = ax1.bar(post, ov, color=[SLATE, AMBER, AMBER, LINEN], width=0.6)
ax1.set_ylabel("與仰臥敏感子載波重疊 (%)", fontsize=11, color=INK)
ax1.set_title("(a) 敏感子載波是「姿態相依」的", fontsize=12, color=INK)
ax1.set_ylim(0, 110)
for bar, v in zip(b, ov):
    ax1.text(bar.get_x() + bar.get_width() / 2, v + 3, f"{v:.0f}%", ha="center",
             fontsize=10, color=INK, fontweight="bold")
ax1.tick_params(axis="x", labelrotation=15)

# (b) posture classification: 1 antenna vs 2 (AX211 MIMO)
labels = ["單天線", "雙天線\n(AX211 MIMO)"]
vals = [r["acc_1ant"] * 100, r["acc_2ant"] * 100]
b2 = ax2.bar(labels, vals, color=[GRAY, GREEN], width=0.5)
ax2.axhline(25, ls="--", color=RED, lw=1)
ax2.text(1.4, 27, "隨機 25%", fontsize=9, color=RED, ha="right")
ax2.set_ylabel("姿態分類正確率 (%)", fontsize=11, color=INK)
ax2.set_title("(b) 姿態分類：第二天線打破鏡像模糊", fontsize=12, color=INK)
ax2.set_ylim(0, 100)
for bar, v in zip(b2, vals):
    ax2.text(bar.get_x() + bar.get_width() / 2, v + 2, f"{v:.0f}%", ha="center",
             fontsize=11, color=INK, fontweight="bold")

# (c) turn gating — headline benefit
labels3 = ["naive\n(含翻身視窗)", "PASS 門控\n(抑制翻身)"]
vals3 = [r["naive_mae"], r["gated_mae"]]
b3 = ax3.bar(labels3, vals3, color=[RED, GREEN], width=0.5)
ax3.set_ylabel("呼吸率誤差 MAE (BPM)", fontsize=11, color=INK)
ax3.set_title(f"(c) 翻身門控：最壞 {r['naive_max']:.0f} BPM 誤差被移除", fontsize=12, color=INK)
ax3.set_ylim(0, max(vals3) * 1.35)
for bar, v in zip(b3, vals3):
    ax3.text(bar.get_x() + bar.get_width() / 2, v + 0.03, f"{v:.2f}", ha="center",
             fontsize=11, color=INK, fontweight="bold")
ax3.annotate("", xy=(1, r["gated_mae"] + 0.08), xytext=(0, r["naive_mae"] + 0.08),
             arrowprops=dict(arrowstyle="->", color=INK, lw=1.4))
ax3.text(0.5, r["naive_mae"] + 0.16,
         f"×{r['naive_mae']/max(r['gated_mae'],1e-6):.1f} 降低",
         ha="center", fontsize=10, color=INK)

# (d) re-selection SNR_eff (honest: modest in single link)
x = np.arange(len(post)); w = 0.26
sf = [r["per_posture"][p]["snr_fixed"] for p in post]
sp = [r["per_posture"][p]["snr_pass"] for p in post]
so = [r["per_posture"][p]["snr_oracle"] for p in post]
ax4.bar(x - w, sf, w, label="FIXED (仰臥)", color=GRAY)
ax4.bar(x,      sp, w, label="PASS (重選)", color=SLATE)
ax4.bar(x + w,  so, w, label="ORACLE", color=GREEN)
ax4.set_xticks(x); ax4.set_xticklabels(post, rotation=15)
ax4.set_ylabel("融合呼吸 SNR_eff", fontsize=11, color=INK)
ax4.set_title("(d) 子載波重選增益（單鏈路偏小 — 誠實）", fontsize=12, color=INK)
ax4.legend(fontsize=9, loc="upper left")

fig.suptitle("姿態感知子載波選擇 (PASS · C2)：翻身偵測 → 姿態分類 → 子載波重選",
             fontsize=14, color=INK, y=0.995)
plt.tight_layout(rect=[0, 0, 1, 0.98])
out = os.path.join(os.path.dirname(__file__), "pass_results.png")
plt.savefig(out, dpi=130, facecolor="#EEEDE9")
print(f"saved {out}")
