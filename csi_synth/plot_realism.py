"""Generate the physics-realism ablation figure."""
import sys, os, numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.font_manager as fm
_cjk="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
try: fm.fontManager.addfont(_cjk); plt.rcParams["font.family"]=fm.FontProperties(fname=_cjk).get_name()
except Exception: pass
plt.rcParams["axes.unicode_minus"]=False
sys.path.insert(0,os.path.dirname(__file__))
import realism_analysis as RA

r20=RA.run(20.0); r10=RA.run(10.0)
labels=["理想化\n(點散射+正弦)","+延展人體","+呼吸變異","+擴散散射\n(Rician)","+背景微動\n(全真實)"]
INK,SLATE,GRAY,RED,GREEN,AMBER="#18191C","#5A6B7A","#8B8F95","#8B2020","#375623","#C55A11"
cols=[GREEN,SLATE,AMBER,AMBER,RED]
m20=[r20[i][1] for i in range(5)]; s20=[r20[i][2] for i in range(5)]
m10=[r10[i][1] for i in range(5)]; s10=[r10[i][2] for i in range(5)]

fig,(ax1,ax2)=plt.subplots(1,2,figsize=(13,5),sharey=True)
fig.patch.set_facecolor("#EEEDE9")
for ax,m,s,snr in [(ax1,m20,s20,20),(ax2,m10,s10,10)]:
    b=ax.bar(labels,m,yerr=s,color=cols,width=0.62,capsize=3,error_kw={"elinewidth":1,"ecolor":"#888"})
    ax.set_title(f"SNR = {snr} dB",fontsize=13,color=INK)
    ax.set_facecolor("#FBFBFA")
    for bar,v in zip(b,m): ax.text(bar.get_x()+bar.get_width()/2,v+0.25,f"{v:.1f}",ha="center",fontsize=10,color=INK,fontweight="bold")
    ax.tick_params(axis="x",labelsize=9)
ax1.set_ylabel("呼吸率誤差 MAE (BPM)",fontsize=12,color=INK)
ax1.annotate("",xy=(4,m20[4]),xytext=(0,m20[0]+0.5),arrowprops=dict(arrowstyle="->",color=RED,lw=1.4,connectionstyle="arc3,rad=-0.2"))
ax1.text(1.7,m20[0]+2.2,f"理想化樂觀 {m20[4]/max(m20[0],0.1):.0f}×",fontsize=10,color=RED)
fig.suptitle("物理真實度消融：理想化模型高估了多少訊號品質",fontsize=14,color=INK,y=1.00)
plt.tight_layout()
plt.savefig("realism_ablation_results.png",dpi=130,facecolor="#EEEDE9",bbox_inches="tight")
print("saved realism_ablation_results.png")
print("20dB:",[f'{x:.2f}' for x in m20])
print("10dB:",[f'{x:.2f}' for x in m10])
