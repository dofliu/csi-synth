"""
twin_new_room.py — Digital-twin simulation of the student's new bedroom
(2026-07-22), using the same physics package that backs the JSX twin, configured
to the reported geometry, then analysed in the student's own ESP-tool 3-panel
style for a side-by-side twin-vs-real comparison. Reproduces figs/twin_vs_real.png.

    cd csi_synth
    PYTHONPATH=. python real_data/second_batch_20260722/twin_new_room.py

Geometry (cm, origin bottom-left corner):
    room 365(x) x 325(y) x 305(z)
    Rx ESP32   = (35, 105, 80)
    Tx N300    = (277, 45, 180)   → 3D LoS 268.6 cm
    subject    = seated in the desk chair (est. floor XY (155, 205); ~126 cm
                 off the Tx-Rx line — a real reason the coupling is modest)

Point of the figure: a CLEAN UNIFORM capture (what the twin assumes) yields a
crisp single breathing peak at the true rate; the real bursty capture does not.
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
from csi_synth import (Room, Node, Person, RadioConfig, generate_csi,
                       NoiseConfig, apply_noise, load_real_csi)
from csi_synth.estimate import bandpass
from csi_synth.twin_import import resample_uniform
from csi_synth.pass_select import select_sensitive, fused_snr_eff

BLUE, RED, GREEN, GRAY = "#2B6CB0", "#C0392B", "#2E7D5B", "#5A6B7A"
NULL = range(23, 32)

room = Room(width=3.65, depth=3.25)
rx, tx = Node(0.35, 1.05), Node(2.77, 0.45)
TRUE_BPM, FS_SIM = 16.0, 30.0
person = Person(1.55, 2.05, breathing={"rate_bpm": TRUE_BPM, "amplitude_mm": 4.0})
cfg = RadioConfig(f_center=2.437e9, bandwidth=20e6, n_subcarriers=52, sample_rate=FS_SIM)
sim = apply_noise(generate_csi(room, tx, rx, person, duration=60.0, config=cfg),
                  NoiseConfig(snr_db=18.0))
amp_sim = sim.amplitude.copy(); amp_sim[:, list(NULL)] = 0.0

real = load_real_csi(os.path.join(HERE, "CSI_breathe_2_20260722_172808.csv"))
real_u = resample_uniform(real, fs=20.0)

def analyse(ax_raw, ax_filt, ax_spec, t, amp, fs, title, col):
    keep = [k for k in range(amp.shape[1]) if k not in NULL]
    m = amp[:, keep].mean(axis=1)
    ax_raw.plot(t, m, color=GRAY, lw=0.8); ax_raw.set_title(title, fontsize=10, loc="left"); ax_raw.set_ylabel("振幅")
    filt = bandpass(m - m.mean(), fs, 0.1, 0.6)
    ax_filt.plot(t, filt, color=col, lw=1.1); ax_filt.set_ylabel("振幅")
    ax_filt.set_title("帶通後呼吸訊號 (0.1–0.6 Hz)", fontsize=9, loc="left")
    T = filt.size; n = np.arange(T); fr = np.arange(0.05, 1.0, 0.004)
    mag = np.array([np.hypot(np.sum(filt*np.cos(2*np.pi*f/fs*n)), np.sum(filt*np.sin(2*np.pi*f/fs*n)))/T for f in fr])
    pk = fr[np.argmax(mag)]
    ax_spec.plot(fr, mag, color=RED, lw=1.4)
    ax_spec.plot(pk, mag.max(), "o", color=GREEN, ms=9, label=f"峰值 {pk:.3f}Hz = {pk*60:.1f} bpm")
    ax_spec.set_xlabel("頻率 (Hz)"); ax_spec.set_ylabel("功率"); ax_spec.legend(fontsize=8, loc="upper right"); ax_spec.set_xlim(0, 1.0)
    return pk * 60

fig, ax = plt.subplots(3, 2, figsize=(13, 8.4))
bpm_s = analyse(ax[0, 0], ax[1, 0], ax[2, 0], sim.t, amp_sim, FS_SIM,
                f"數位孿生模擬（新臥室幾何, 乾淨均勻 {FS_SIM:.0f}Hz, 真值 {TRUE_BPM:.0f}bpm）", BLUE)
bpm_r = analyse(ax[0, 1], ax[1, 1], ax[2, 1], real_u.t, real_u.amplitude, 20.0,
                "學生實測 breathe2（重取樣均勻 20Hz）", GREEN)
snr_s = fused_snr_eff(amp_sim, select_sensitive(amp_sim, k=8, fs=FS_SIM, band=(0.1, 0.6)), fs=FS_SIM, band=(0.1, 0.6))
snr_r = fused_snr_eff(real_u.amplitude, select_sensitive(real_u.amplitude, k=8, fs=20.0, band=(0.1, 0.6)), fs=20.0, band=(0.1, 0.6))
fig.suptitle(f"數位孿生（新房間）vs 學生實測 —— 同一套 3 步驟分析\n"
             f"孿生: 回收 {bpm_s:.1f}bpm(真值{TRUE_BPM:.0f}) SNR={snr_s:.1f} 峰清楚  |  "
             f"實測: {bpm_r:.1f}bpm SNR={snr_r:.1f} 峰不明顯（爆發式取樣+坐姿離線）", fontsize=12, y=0.995)
fig.tight_layout(rect=[0, 0, 1, 0.94])
out = os.path.join(HERE, "figs", "twin_vs_real.png")
fig.savefig(out, bbox_inches="tight"); print("wrote", out, f"| sim {bpm_s:.1f}bpm SNR{snr_s:.1f} | real {bpm_r:.1f}bpm SNR{snr_r:.1f}")
