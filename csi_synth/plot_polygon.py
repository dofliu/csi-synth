"""Coverage-map figure: rectangular vs L-shaped sensing coverage."""
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
from csi_synth.polygon import rect_room, l_room

tx,rx=(5.5,1.0),(0.5,1.0)
rooms=[("矩形房間",rect_room(6,5)),("L 形房間（有內凹角）",l_room(6,5,2.5,2.0))]
fig,axes=plt.subplots(1,2,figsize=(13,5.2))
fig.patch.set_facecolor("#EEEDE9")

for ax,(name,room) in zip(axes,rooms):
    xs,ys,Z=PA.coverage_map(room,tx,rx,nx=52,ny=42)
    # log-scale for dynamic range; normalize to peak
    Zn=np.log10(Z/np.nanmax(Z)+1e-6)
    im=ax.pcolormesh(xs,ys,Zn,cmap="magma",vmin=-3,vmax=0,shading="auto")
    # room outline
    verts=[tuple(v) for v in room.V]
    ax.add_patch(MplPoly(verts,fill=False,edgecolor="#EEEDE9",lw=2.5))
    # tx/rx
    ax.plot(*tx,marker="^",ms=13,color="#39FF14",mec="black",mew=0.8);ax.text(tx[0],tx[1]-0.32,"Tx",ha="center",color="white",fontsize=10,fontweight="bold")
    ax.plot(*rx,marker="v",ms=13,color="#00E5FF",mec="black",mew=0.8);ax.text(rx[0],rx[1]-0.32,"Rx",ha="center",color="white",fontsize=10,fontweight="bold")
    # reflex corner
    for _,C in room.reflex_corners():
        ax.plot(*C,marker="o",ms=10,color="#FF3B30",mec="white",mew=1)
        ax.text(C[0]+0.1,C[1]+0.15,"內凹角\n(繞射源)",color="#FF3B30",fontsize=9,fontweight="bold")
    ax.set_title(name,fontsize=13,color="#18191C")
    ax.set_aspect("equal");ax.set_xlabel("x (m)");ax.set_ylabel("y (m)")
    ax.set_facecolor("#111")
cbar=fig.colorbar(im,ax=axes,fraction=0.025,pad=0.02)
cbar.set_label("呼吸訊號強度 (log, 相對峰值)",fontsize=10)
fig.suptitle("感測覆蓋圖：L 形房間在內凹角後方出現遮蔽死角（訊號僅靠繞射微弱抵達）",fontsize=13.5,color="#18191C",y=1.02)
plt.savefig("polygon_coverage_results.png",dpi=130,facecolor="#EEEDE9",bbox_inches="tight")
print("saved polygon_coverage_results.png")
# print coverage stats
for name,room in rooms:
    xs,ys,Z=PA.coverage_map(room,tx,rx,nx=40,ny=32);v=Z[~np.isnan(Z)]
    print(f'{name}: coverage(>5% peak)={np.mean(v>np.nanmax(Z)*0.05)*100:.1f}%')
