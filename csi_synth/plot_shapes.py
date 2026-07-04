"""Compare sensing coverage across room shapes: rect / partition / slanted (+ L)."""
import sys, os, numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.font_manager as fm
from matplotlib.patches import Polygon as MplPoly
_cjk="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
try: fm.fontManager.addfont(_cjk); plt.rcParams["font.family"]=fm.FontProperties(fname=_cjk).get_name()
except Exception: pass
plt.rcParams["axes.unicode_minus"]=False
sys.path.insert(0,os.path.dirname(__file__))
import polygon_analysis as PA
from csi_synth.polygon import rect_room, partition_room, slanted_room

tx,rx=(1.0,1.0),(5.0,1.0)   # opposite sides, low — maximally tests occlusion
shapes=[("矩形（基準）",rect_room(6,5)),
        ("隔間（內牆+門洞）",partition_room(6,5,3.0,1.2)),
        ("斜牆（梯形，凸）",slanted_room(6,5,2.0))]

fig,axes=plt.subplots(1,3,figsize=(15,4.8))
fig.patch.set_facecolor("#EEEDE9")
stats=[]
for ax,(name,room) in zip(axes,shapes):
    xs,ys,Z=PA.coverage_map(room,tx,rx,nx=50,ny=40)
    peak=np.nanmax(Z); Zn=np.log10(Z/peak+1e-6)
    im=ax.pcolormesh(xs,ys,Zn,cmap="magma",vmin=-3,vmax=0,shading="auto")
    ax.add_patch(MplPoly([tuple(v) for v in room.V],fill=False,edgecolor="#EEEDE9",lw=2.5))
    for (a,b) in room.interior:  # partition wall
        ax.plot([a[0],b[0]],[a[1],b[1]],color="#FF3B30",lw=3)
        ax.text(a[0]+0.1,(a[1]+b[1])/2,"隔間",color="#FF3B30",fontsize=9,fontweight="bold",rotation=90,va="center")
    for e in room.diffracting_edges():
        ax.plot(*e,marker="o",ms=8,color="#FFD60A",mec="black",mew=0.8)
    ax.plot(*tx,marker="^",ms=12,color="#39FF14",mec="black");ax.text(tx[0],tx[1]-0.35,"Tx",ha="center",color="white",fontsize=9,fontweight="bold")
    ax.plot(*rx,marker="v",ms=12,color="#00E5FF",mec="black");ax.text(rx[0],rx[1]-0.35,"Rx",ha="center",color="white",fontsize=9,fontweight="bold")
    v=Z[~np.isnan(Z)];cover=np.mean(v>peak*0.05)*100;stats.append((name,cover))
    ax.set_title(f"{name}\n可用覆蓋 {cover:.0f}%",fontsize=12,color="#18191C")
    ax.set_aspect("equal");ax.set_xlabel("x (m)");ax.set_facecolor("#111")
axes[0].set_ylabel("y (m)")
cbar=fig.colorbar(im,ax=axes,fraction=0.02,pad=0.02);cbar.set_label("呼吸訊號強度 (log)",fontsize=10)
fig.suptitle("房間形狀對感測覆蓋的影響（Tx/Rx 分置兩側低處）",fontsize=13.5,color="#18191C",y=1.04)
plt.savefig("shape_comparison_results.png",dpi=125,facecolor="#EEEDE9",bbox_inches="tight")
print("saved shape_comparison_results.png")
for name,c in stats: print(f'  {name}: {c:.1f}%')
