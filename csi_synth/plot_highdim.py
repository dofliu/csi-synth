"""High-dimensional CSI figure: the sensitivity spectrum and independent looks."""
import sys, os, numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.font_manager as fm
_cjk="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
try: fm.fontManager.addfont(_cjk); plt.rcParams["font.family"]=fm.FontProperties(fname=_cjk).get_name()
except Exception: pass
plt.rcParams["axes.unicode_minus"]=False
sys.path.insert(0,os.path.dirname(__file__))
import highdim_analysis as H

INK,SLATE,GRAY,RED,GREEN,AMBER="#18191C","#5A6B7A","#8B8F95","#8B2020","#375623","#C55A11"

# pick a channel with a clear fade near F0 for the illustration
rng=np.random.default_rng(11)
for _ in range(40):
    d,g=H.make_static_multipath(rng); pd=rng.uniform(15e-9,45e-9)
    fine=H.device_subcarriers(4096,H.FULL_BW); S=H.sensitivity_spectrum(fine,d,g,pd)
    # want a fade within a plausible 20MHz window
    if S.min()/S.max()<0.15: break
thr=0.5*S.max()
fMHz=(fine-H.F0)/1e6

best,looks,blind,ex,ng=H.run()

fig=plt.figure(figsize=(13,6.6)); fig.patch.set_facecolor("#EEEDE9")
gs=fig.add_gridspec(2,3,height_ratios=[2.1,1.0],width_ratios=[1,1,1],hspace=0.55,wspace=0.35)

# ── top: sensitivity spectrum ──
ax=fig.add_subplot(gs[0,:])
ax.plot(fMHz,S,color=INK,lw=1.3)
ax.axhline(thr,color=GRAY,ls=":",lw=1)
ax.fill_between(fMHz,0,S,where=S>=thr,color=SLATE,alpha=0.15)
# AX211 spans full band
ax211=H.device_subcarriers(256,160e6); ax.plot((ax211-H.F0)/1e6,np.interp((ax211-H.F0)/1e6,fMHz,S),
        "o",ms=2.4,color=SLATE,label="AX211 · 256 子載波 / 160 MHz")
# a 20MHz narrowband device sitting on one channel (pick a centre in a fade)
nbc=fMHz[np.argmin(np.abs(S-S.min()))]  # centre near a fade
nb=np.linspace(nbc-10,nbc+10,56)
ax.axvspan(nbc-10,nbc+10,color=RED,alpha=0.10)
ax.plot(nb,np.interp(nb,fMHz,S),"o",ms=3,color=RED,label="20 MHz 窄頻裝置（單一通道）")
ax.set_title("呼吸靈敏度頻譜 S(f)：寬頻涵蓋多個獨立衰落，窄頻只看到一小片",fontsize=13,color=INK)
ax.set_xlabel("相對頻率 (MHz，中心 5.5 GHz)"); ax.set_ylabel("靈敏度 S(f)")
ax.legend(loc="upper right",fontsize=9); ax.set_facecolor("#FBFBFA"); ax.set_xlim(-80,80); ax.set_ylim(0,S.max()*1.15)
ax.annotate("窄頻落在衰落 →\n可用子載波少",xy=(nbc,S.min()+0.02*S.max()),xytext=(nbc-3,S.max()*0.7),
            fontsize=9,color=RED,ha="center",arrowprops=dict(arrowstyle="->",color=RED,lw=1))

# ── bottom-left: independent looks bar ──
axb=fig.add_subplot(gs[1,0])
names=["5300","ESP32","AX211"]; vals=[np.mean(looks[n]) for n in ["Intel 5300","ESP32","AX211 (6E)"]]
b=axb.bar(names,vals,color=[GRAY,AMBER,SLATE],width=0.62)
for bar,v in zip(b,vals): axb.text(bar.get_x()+bar.get_width()/2,v+0.6,f"{v:.0f}",ha="center",fontsize=11,fontweight="bold",color=INK)
axb.set_title("獨立敏感 looks（分集）",fontsize=11,color=INK); axb.set_facecolor("#FBFBFA"); axb.set_ylim(0,32)

# ── bottom-mid: best-of-K ──
axc=fig.add_subplot(gs[1,1])
vals2=[np.mean(best[n]) for n in ["Intel 5300","ESP32","AX211 (6E)"]]
b2=axc.bar(names,vals2,color=[GRAY,AMBER,SLATE],width=0.62)
for bar,v in zip(b2,vals2): axc.text(bar.get_x()+bar.get_width()/2,v+0.02,f"{v:.2f}",ha="center",fontsize=11,fontweight="bold",color=INK)
axc.set_title("best-of-K（找到最佳子載波）",fontsize=11,color=INK); axc.set_facecolor("#FBFBFA"); axc.set_ylim(0,1.15)

# ── bottom-right: takeaway text ──
axt=fig.add_subplot(gs[1,2]); axt.axis("off")
axt.text(0,0.95,"誠實結論",fontsize=12,fontweight="bold",color=SLATE,va="top")
axt.text(0,0.66,"窄頻並非無望——通常仍能\n找到一條敏感子載波(0.96)。",fontsize=9.5,color=INK,va="top")
axt.text(0,0.28,"真正的增益是 ~8× 獨立分集，\n餵給多子載波融合(SNR_eff)\n與魯棒性。",fontsize=9.5,color=INK,va="top")

fig.suptitle("256 子載波「多找幾條敏感路徑」——是頻率分集，不是找到唯一好子載波",fontsize=14,color=INK,y=0.99)
plt.savefig("highdim_results.png",dpi=125,facecolor="#EEEDE9",bbox_inches="tight")
print("saved highdim_results.png")
print("independent looks:",{n:round(np.mean(looks[n]),1) for n in ["Intel 5300","ESP32","AX211 (6E)"]})
