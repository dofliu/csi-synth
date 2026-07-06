"""Generate the consolidated benchmark figure."""
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
import benchmark as B

res = B.run_benchmark(seeds=8, verbose=True)
rows = res["rows"]
INK, SLATE, LINEN, GRAY, RED, GREEN, AMBER = \
    "#18191C", "#5A6B7A", "#B8B0A4", "#8B8F95", "#8B2020", "#375623", "#C55A11"
COL = {"ESP32": GRAY, "AX210": AMBER, "AX211": SLATE}
PANEL = "#FBFBFA"


def cell(hw, scen, real, key):
    xs, ys = [], []
    for snr in res["snrs"]:
        c = [r for r in rows if r["hardware"] == hw and r["scenario"] == scen
             and r["realism"] == real and r["snr_db"] == snr]
        if c:
            xs.append(snr); ys.append(c[0][key])
    return xs, ys


fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(13, 9))
fig.patch.set_facecolor("#EEEDE9")
for ax in (ax1, ax2, ax3, ax4):
    ax.set_facecolor(PANEL)

# (a) detection floor — the headline
hws = list(B.HARDWARE)
floors = [res["floors"][h] if res["floors"][h] is not None else max(res["snrs"]) + 2 for h in hws]
b = ax1.bar(hws, floors, color=[COL[h] for h in hws], width=0.6)
ax1.set_ylabel("偵測門檻 SNR (dB, 越低越好)", fontsize=11, color=INK)
ax1.set_title("(a) 偵測門檻：寬頻裝置偵測更深入雜訊", fontsize=12, color=INK)
for bar, f, h in zip(b, floors, hws):
    ax1.text(bar.get_x() + bar.get_width() / 2, f + 0.3,
             f"{res['floors'][h]}dB" if res['floors'][h] is not None else ">max",
             ha="center", fontsize=11, color=INK, fontweight="bold")
ax1.text(0.5, 0.92, f"{B.HARDWARE['ESP32']} vs {B.HARDWARE['AX211']} 子載波",
         transform=ax1.transAxes, ha="center", fontsize=9, color=GRAY)

# (b) rate MAE vs SNR (supine / ideal)
for h in hws:
    xs, ys = cell(h, "supine", "ideal", "rate_mae")
    ax2.plot(xs, ys, "o-", color=COL[h], label=h, lw=1.6)
ax2.set_xlabel("SNR (dB)", fontsize=10, color=INK)
ax2.set_ylabel("呼吸率 MAE (BPM)", fontsize=11, color=INK)
ax2.set_title("(b) 呼吸率精度 vs SNR（仰臥/理想）", fontsize=12, color=INK)
ax2.legend(fontsize=9); ax2.set_ylim(bottom=0)

# (c) detection rate vs SNR (supine): ideal solid, physical dashed
for h in hws:
    xs, ys = cell(h, "supine", "ideal", "detect_rate")
    ax3.plot(xs, [y * 100 for y in ys], "o-", color=COL[h], label=f"{h} 理想", lw=1.6)
    xs, ys = cell(h, "supine", "physical", "detect_rate")
    ax3.plot(xs, [y * 100 for y in ys], "s--", color=COL[h], alpha=0.6, lw=1.2)
ax3.axhline(90, ls=":", color=RED, lw=1); ax3.text(res["snrs"][-1], 91, "90%", color=RED, fontsize=8, ha="right")
ax3.set_xlabel("SNR (dB)", fontsize=10, color=INK)
ax3.set_ylabel("偵測率 (%)", fontsize=11, color=INK)
ax3.set_title("(c) 偵測率 vs SNR（實線=理想, 虛線=物理真實）", fontsize=12, color=INK)
ax3.legend(fontsize=8, loc="lower right"); ax3.set_ylim(0, 105)

# (d) sim-to-real gap: ideal vs physical mean detect rate (over all cells)
ideal = np.mean([r["detect_rate"] for r in rows if r["realism"] == "ideal"]) * 100
phys = np.mean([r["detect_rate"] for r in rows if r["realism"] == "physical"]) * 100
bb = ax4.bar(["理想\n(點散射+正弦)", "物理真實層\n(延展體+擴散+背景)"], [ideal, phys],
             color=[LINEN, RED], width=0.5)
ax4.set_ylabel("平均偵測率 (%)", fontsize=11, color=INK)
ax4.set_title("(d) sim-to-real 落差：物理真實層明顯更難", fontsize=12, color=INK)
ax4.set_ylim(0, 105)
for bar, v in zip(bb, [ideal, phys]):
    ax4.text(bar.get_x() + bar.get_width() / 2, v + 2, f"{v:.0f}%", ha="center",
             fontsize=11, color=INK, fontweight="bold")

fig.suptitle("csi_synth 統一基準：跨 硬體 × SNR × 姿態 × 真實度 的生命徵象感測效果",
             fontsize=13, color=INK, y=0.995)
plt.tight_layout(rect=[0, 0, 1, 0.97])
out = os.path.join(os.path.dirname(__file__), "benchmark_results.png")
plt.savefig(out, dpi=130, facecolor="#EEEDE9")
B._write_csv(res, os.path.join(os.path.dirname(__file__), "benchmark_results.csv"))
print(f"saved {out}")
