"""Generate the site-calibration results figure for the thesis."""
import sys, os, numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.font_manager as fm
_cjk="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
try: fm.fontManager.addfont(_cjk); plt.rcParams["font.family"]=fm.FontProperties(fname=_cjk).get_name()
except Exception: pass
plt.rcParams["axes.unicode_minus"]=False
sys.path.insert(0,os.path.dirname(__file__))
import site_calibration as SC
r=SC.run_experiment()

INK,SLATE,LINEN,GRAY,RED,GREEN="#18191C","#5A6B7A","#B8B0A4","#8B8F95","#8B2020","#375623"
fig,(ax1,ax2)=plt.subplots(1,2,figsize=(13,5),gridspec_kw={"width_ratios":[3,2]})
fig.patch.set_facecolor("#EEEDE9")

# left: main comparison
labels=["通用模型\n(跨房間)","少量校準\n(few-shot)","空間專屬\n(site)","oracle\n(上限)"]
vals=[r["generic"],r["fewshot"],r["site"],r["oracle"]]
cols=[GRAY,LINEN,SLATE,GREEN]
b=ax1.bar(labels,vals,color=cols,width=0.62)
ax1.set_ylabel("呼吸率誤差 MAE (BPM)",fontsize=12,color=INK)
ax1.set_title("空間校準的增益（越低越好）· 6 dB 低SNR",fontsize=13,color=INK)
for bar,v in zip(b,vals): ax1.text(bar.get_x()+bar.get_width()/2,v+0.05,f"{v:.2f}",ha="center",fontsize=11,color=INK,fontweight="bold")
ax1.set_facecolor("#FBFBFA"); ax1.set_ylim(0,max(vals)*1.25)
ax1.annotate("",xy=(2,r["site"]+0.15),xytext=(0,r["generic"]+0.15),arrowprops=dict(arrowstyle="->",color=RED,lw=1.5))
ax1.text(1,r["generic"]+0.28,f"↓ {r['generic']-r['site']:.2f} BPM\n約 {r['generic']/r['site']:.1f}× 精度",ha="center",fontsize=10,color=RED)

# right: fragility + recal
labels2=["空間專屬\n(原房間)","感測器移動\n(未校準)","重新校準\n(移動後)"]
vals2=[r["site"],r["site_moved"],r["recal"]]
cols2=[SLATE,RED,GREEN]
b2=ax2.bar(labels2,vals2,color=cols2,width=0.6)
ax2.set_ylabel("呼吸率誤差 MAE (BPM)",fontsize=12,color=INK)
ax2.set_title("脆弱性與重新校準",fontsize=13,color=INK)
for bar,v in zip(b2,vals2): ax2.text(bar.get_x()+bar.get_width()/2,v+0.04,f"{v:.2f}",ha="center",fontsize=11,color=INK,fontweight="bold")
ax2.set_facecolor("#FBFBFA"); ax2.set_ylim(0,max(vals2)*1.3)

plt.tight_layout()
plt.savefig("site_calibration_results.png",dpi=130,facecolor="#EEEDE9")
print("\nSaved site_calibration_results.png")
