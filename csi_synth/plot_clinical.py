"""Clinical-scenario figure: envelope over a night + per-event detection."""
import sys, os, numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.font_manager as fm
from matplotlib.patches import Patch
_cjk="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
try: fm.fontManager.addfont(_cjk); plt.rcParams["font.family"]=fm.FontProperties(fname=_cjk).get_name()
except Exception: pass
plt.rcParams["axes.unicode_minus"]=False
sys.path.insert(0,os.path.dirname(__file__))
import clinical_analysis as CA
from csi_synth.clinical import (SleepBreathingModel, generate_clinical_csi, EVENT_NAMES,
                                NORMAL,HYPOPNEA,APNEA_OSA,APNEA_CSA)
from csi_synth.geometry import Room, Node
from csi_synth.generator import RadioConfig

INK,SLATE,GRAY,RED,GREEN,AMBER="#18191C","#5A6B7A","#8B8F95","#8B2020","#375623","#C55A11"
ECOL={HYPOPNEA:AMBER,APNEA_OSA:RED,APNEA_CSA:SLATE}
ENAME={HYPOPNEA:"低通氣",APNEA_OSA:"阻塞型OSA",APNEA_CSA:"中樞型CSA"}

# one representative night
m=SleepBreathingModel(rate_bpm=15,amplitude_mm=5,seed=101)
ev=CA.build_night(0)
amp,mask,t=generate_clinical_csi(Room(5,4),Node(0.6,2.0),Node(4.4,2.0),(2.2,1.6),m,ev,
                                 duration=180,radio=RadioConfig(n_subcarriers=64,sample_rate=20),snr_db=22,seed=201)
env=CA.respiratory_envelope(amp)
base=np.median(env[mask==NORMAL])

env_by,hits,totals=CA.analyze(n_seeds=5,snr_db=22.0)

fig,(ax1,ax2)=plt.subplots(2,1,figsize=(12,7),gridspec_kw={"height_ratios":[2,1.3]})
fig.patch.set_facecolor("#EEEDE9")

# panel 1: envelope over the night
ax1.plot(t,env,color=INK,lw=1.1)
ax1.axhline(0.5*base,color=RED,ls="--",lw=1,label="偵測門檻 (0.5×正常)")
for e in ev:
    ax1.axvspan(e.start,e.start+e.duration,color=ECOL[e.kind],alpha=0.22)
    ax1.text(e.start+e.duration/2,env.max()*0.96,ENAME[e.kind],ha="center",fontsize=9,color=ECOL[e.kind],fontweight="bold")
ax1.set_xlabel("時間 (s)",fontsize=11); ax1.set_ylabel("呼吸動作包絡線",fontsize=11)
ax1.set_title("一夜的呼吸動作包絡線：CSA 塌陷可偵測，OSA 動作持續被漏掉",fontsize=12.5,color=INK)
ax1.legend(loc="upper right",fontsize=9); ax1.set_facecolor("#FBFBFA"); ax1.set_xlim(0,180)

# panel 2: sensitivity per event type
codes=[APNEA_CSA,HYPOPNEA,APNEA_OSA]
names=["中樞型CSA\n(動作停止)","低通氣\n(部分降低)","阻塞型OSA\n(動作持續)"]
sens=[hits[c]/max(totals[c],1)*100 for c in codes]
cols=[GREEN,AMBER,RED]
b=ax2.bar(names,sens,color=cols,width=0.6)
for bar,v in zip(b,sens): ax2.text(bar.get_x()+bar.get_width()/2,v+2,f"{v:.0f}%",ha="center",fontsize=11,fontweight="bold",color=INK)
ax2.set_ylabel("naive偵測器敏感度",fontsize=11); ax2.set_ylim(0,112)
ax2.set_title("動作型偵測器：抓到中樞型，卻漏掉臨床主要的 OSA 與低通氣",fontsize=12.5,color=INK)
ax2.set_facecolor("#FBFBFA")
plt.tight_layout()
plt.savefig("clinical_scenario_results.png",dpi=130,facecolor="#EEEDE9",bbox_inches="tight")
print("saved clinical_scenario_results.png")
