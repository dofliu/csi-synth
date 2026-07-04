"""
demo_visualize.py — Generate synthetic CSI and plot it, to eyeball the output.

Produces a 4-panel figure:
    (1) CSI amplitude heatmap (subcarrier x time)
    (2) Selected subcarrier amplitude over time (clean vs noisy)
    (3) DFT spectrum with detected breathing peak
    (4) Apnea scenario: amplitude with apnea segments shaded

Saves to csi_synth_demo.png
"""
import sys, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# Register a CJK font so Chinese labels render properly
_cjk = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
try:
    fm.fontManager.addfont(_cjk)
    plt.rcParams["font.family"] = fm.FontProperties(fname=_cjk).get_name()
except Exception:
    pass
plt.rcParams["axes.unicode_minus"] = False

sys.path.insert(0, os.path.dirname(__file__))
from csi_synth import (Room, Node, Person, RadioConfig, generate_csi,
                       NoiseConfig, apply_noise, estimate_rate, make_scenario)

# dof-podium-ish palette
INK, SLATE, LINEN, GRAY = "#18191C", "#5A6B7A", "#B8B0A4", "#8B8F95"

room = Room(5, 4)
tx, rx = Node(0.6, 2.0), Node(4.4, 2.0)
cfg = RadioConfig(n_subcarriers=64, sample_rate=100.0)

# Breathing person
person = Person(2.5, 2.0, breathing={"rate_bpm": 15.0, "amplitude_mm": 5.0})
clean = generate_csi(room, tx, rx, person, duration=30, config=cfg,
                     label={"br_bpm": 15.0})
noisy = apply_noise(clean, NoiseConfig(snr_db=22, cfo_hz=200, sfo_ppm=5,
                                       agc_std=0.03, seed=1))

est = estimate_rate(noisy, band=(0.1, 0.6))
k = est["subcarrier"]

fig, ax = plt.subplots(2, 2, figsize=(13, 8))
fig.patch.set_facecolor("#EEEDE9")

# (1) Heatmap
im = ax[0, 0].imshow(noisy.amplitude.T, aspect="auto", cmap="bone_r",
                     extent=[0, 30, 0, cfg.n_subcarriers], origin="lower")
ax[0, 0].set_title("CSI 振幅熱圖（含雜訊）", fontsize=12, color=INK)
ax[0, 0].set_xlabel("時間 (s)"); ax[0, 0].set_ylabel("子載波")
fig.colorbar(im, ax=ax[0, 0], fraction=0.04)

# (2) Time series clean vs noisy
ax[0, 1].plot(clean.t, clean.amplitude[:, k], color=LINEN, lw=1.5, label="乾淨")
ax[0, 1].plot(noisy.t, noisy.amplitude[:, k], color=SLATE, lw=1.0, label="含雜訊")
ax[0, 1].set_title(f"子載波 {k} 振幅時間序列", fontsize=12, color=INK)
ax[0, 1].set_xlabel("時間 (s)"); ax[0, 1].set_ylabel("振幅"); ax[0, 1].legend()

# (3) DFT spectrum
mask = (est["freqs"] >= 0) & (est["freqs"] <= 0.8)
ax[1, 0].plot(est["freqs"][mask] * 60, est["spectrum"][mask], color=SLATE, lw=1.5)
ax[1, 0].axvline(15.0, color=INK, ls="--", lw=1, label="設定 15 BPM")
ax[1, 0].axvline(est["bpm"], color="#8B2020", ls=":", lw=1.5,
                 label=f"估算 {est['bpm']:.1f} BPM")
ax[1, 0].set_title("呼吸頻率 DFT 頻譜", fontsize=12, color=INK)
ax[1, 0].set_xlabel("頻率 (BPM)"); ax[1, 0].set_ylabel("幅值"); ax[1, 0].legend()

# (4) Apnea scenario
apnea = make_scenario("apnea-event", duration=90.0, config=cfg)
mask_a = np.array(apnea.label["apnea_mask"])
ka = int(np.argmax(np.var(apnea.amplitude, axis=0)))
ax[1, 1].plot(apnea.t, apnea.amplitude[:, ka], color=SLATE, lw=0.8)
# shade apnea segments
in_ap = False
for i, m in enumerate(mask_a):
    if m and not in_ap:
        start = apnea.t[i]; in_ap = True
    elif not m and in_ap:
        ax[1, 1].axvspan(start, apnea.t[i], color="#8B2020", alpha=0.15)
        in_ap = False
ax[1, 1].set_title("呼吸中止情境（紅色=憋氣段）", fontsize=12, color=INK)
ax[1, 1].set_xlabel("時間 (s)"); ax[1, 1].set_ylabel("振幅")

for a in ax.flat:
    a.set_facecolor("#FBFBFA")

plt.tight_layout()
plt.savefig("csi_synth_demo.png", dpi=130, facecolor="#EEEDE9")
print(f"Saved csi_synth_demo.png")
print(f"Set BR=15.0, estimated {est['bpm']:.2f} BPM on subcarrier {k}")
print(f"Apnea events in ground truth: {apnea.label['n_events']}")
