"""
make_deploy_figs.py — regenerate the deployment figures for DEPLOYMENT.md.

    cd csi_synth
    PYTHONPATH=. python deployment/make_deploy_figs.py

Produces figs/topo_options.png (4 topologies, C = target) and
figs/deploy_arch.png (the C-centric end-to-end system stack).
"""
import os
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.font_manager as fm
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle
for _p in ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
           "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
    if os.path.exists(_p):
        fm.fontManager.addfont(_p); plt.rcParams["font.family"] = [fm.FontProperties(fname=_p).get_name()]; break
plt.rcParams["axes.unicode_minus"] = False

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "figs")
os.makedirs(OUT, exist_ok=True)
INK="#18191C"; SLATE="#5A6B7A"; BLUE="#2B6CB0"; GREEN="#2E7D5B"; RED="#C0392B"; AMBER="#B8860B"

# ══════════════════ FIG 1: four topologies (C = target) ══════════════════
fig, axes = plt.subplots(1, 4, figsize=(16, 5.4))
def room(ax):
    ax.set_xlim(0,10); ax.set_ylim(0,10); ax.axis("off")
    ax.add_patch(FancyBboxPatch((0.4,2.0),9.2,6.4,boxstyle="round,pad=0.1,rounding_size=0.3",
                 fill=False,edgecolor="#bbb",lw=1.4))
def dev(ax,x,y,c,lab,new=True):
    ax.add_patch(FancyBboxPatch((x-0.7,y-0.45),1.4,0.9,boxstyle="round,pad=0.05,rounding_size=0.15",
                 facecolor=("#fff" if new else "#EDEDED"),edgecolor=c,lw=2.3 if new else 1.5))
    ax.text(x,y,lab,ha="center",va="center",fontsize=8.3,color=c,weight="bold")
def person(ax,x,y):
    ax.add_patch(Circle((x,y),0.42,facecolor=GREEN,edgecolor="none")); ax.text(x,y-1.0,"病人",ha="center",fontsize=8,color=GREEN)
def link(ax,x1,y1,x2,y2,c,dashed=False,txt=""):
    ax.add_patch(FancyArrowPatch((x1,y1),(x2,y2),arrowstyle="-",lw=2,color=c,linestyle=(":" if dashed else "-")))
    if txt: ax.text((x1+x2)/2,(y1+y2)/2+0.4,txt,ha="center",fontsize=7.3,color=c)
def verdict(ax,mark,color,title,sub):
    ax.text(5,1.35,mark+"  "+title,ha="center",fontsize=10.8,color=color,weight="bold")
    ax.text(5,0.4,sub,ha="center",fontsize=8.2,color="#444")
def head(ax,t,c): ax.text(5,9.4,t,ha="center",fontsize=11.3,weight="bold",color=c)

a=axes[0]; room(a); head(a,"A. 專用 Tx + 專用 Rx","#999")
dev(a,2.2,6.8,SLATE,"專用Tx"); dev(a,7.8,6.8,SLATE,"專用Rx"); person(a,5,5.2)
link(a,2.9,6.8,4.6,5.4,SLATE); link(a,5.4,5.4,7.1,6.8,GREEN)
verdict(a,"×","#B23B3B","難接受","另加 2 台裝置")

b=axes[1]; room(b); head(b,"B. 現有 AP + 1 顆感測器","#2E7D5B")
dev(b,2.2,6.8,SLATE,"現有AP\n(照明)",new=False); dev(b,7.8,6.8,GREEN,"ESP32\n感測貼片"); person(b,5,5.2)
link(b,2.9,6.8,4.6,5.4,SLATE); link(b,5.4,5.4,7.1,6.8,GREEN)
link(b,7.1,7.25,3.0,7.25,AMBER,dashed=True,txt="主動探測→均勻取樣")
verdict(b,"○","#2E7D5B","過渡原型·現在能做","加 1 個小盒/床")

c=axes[2]; room(c); head(c,"C. 802.11bf 感測 AP（韌體）","#2B6CB0")
# target badge
c.add_patch(FancyBboxPatch((0.4,2.0),9.2,6.4,boxstyle="round,pad=0.1,rounding_size=0.3",
            fill=False,edgecolor=BLUE,lw=2.6))
c.text(5,8.75,"★ 本專案目標架構",ha="center",fontsize=9.5,weight="bold",color=BLUE)
dev(c,2.2,6.5,BLUE,"現有AP\n韌體升級",new=False); dev(c,7.8,6.5,SLATE,"現有裝置\n電視/IoT/手機",new=False); person(c,5,5.0)
link(c,2.9,6.5,4.6,5.2,BLUE); link(c,5.4,5.2,7.1,6.5,SLATE)
link(c,7.1,6.95,3.0,6.95,AMBER,dashed=True,txt="AP 排程 sounding→天生均勻")
verdict(c,"◎","#2B6CB0","近未來·零新硬體","AP 內建感測")

d=axes[3]; room(d); head(d,"D. 單顆毫米波雷達","#B8860B")
dev(d,5,7.0,AMBER,"mmWave\n收發合一"); person(d,5,4.8); link(d,5,6.55,5,5.35,AMBER)
verdict(d,"○","#B8860B","要加硬體不如直接上","一盒·但非 WiFi")

fig.suptitle("部署拓樸選項 —— C（善用現有 AP）為目標，D 為「若必須外加硬體」的替代",fontsize=14,weight="bold",y=1.02)
fig.text(0.5,-0.03,"初衷：大家都有 Wi-Fi AP，善用它做感測。C 用 802.11bf 排程 sounding 讓現有 AP 天生均勻取樣，"
         "既不外加硬體、又避開被動蹭流量的爆發式取樣問題（我們實測到會毀掉呼吸估計）",
         ha="center",fontsize=8.8,color=SLATE)
fig.tight_layout(); fig.savefig(os.path.join(OUT,"topo_options.png"),bbox_inches="tight",dpi=125)
plt.close(fig)

# ══════════════════ FIG 2: C-centric end-to-end stack ══════════════════
fig, ax = plt.subplots(figsize=(13, 8.8)); ax.set_xlim(0,100); ax.set_ylim(0,100); ax.axis("off")
def box(x,y,w,h,fc,ec,title,body="",tsize=11,bsize=8.5,tcol=INK):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0.4,rounding_size=1.5",facecolor=fc,edgecolor=ec,lw=1.7))
    ax.text(x+w/2,y+h-3.0,title,ha="center",va="top",fontsize=tsize,weight="bold",color=tcol)
    if body: ax.text(x+w/2,y+h-6.6,body,ha="center",va="top",fontsize=bsize,color="#333",linespacing=1.4)
def arr(x1,y1,x2,y2,txt="",col=SLATE):
    ax.add_patch(FancyArrowPatch((x1,y1),(x2,y2),arrowstyle="-|>",mutation_scale=16,color=col,lw=1.8,shrinkA=2,shrinkB=2))
    if txt: ax.text((x1+x2)/2+0.3,(y1+y2)/2+1.3,txt,ha="center",fontsize=8,color=col)
for (yy,hh,cc,lab) in [(72,26,"#EAF1F8","① 病房（善用現有 AP · 802.11bf 感測）"),
                       (49,20,"#E8F1EC","② 邊緣運算（可整合進 AP / 房內閘道）"),
                       (28,18,"#F3EFE6","③ 院內網路 + 後端伺服器"),
                       (6,19,"#F4E9E9","④ 臨床端")]:
    ax.add_patch(FancyBboxPatch((2,yy),96,hh,boxstyle="round,pad=0.2,rounding_size=1",facecolor=cc,edgecolor="none",alpha=0.55))
    ax.text(3.5,yy+hh-1.5,lab,ha="left",va="top",fontsize=10.5,weight="bold",color=SLATE)
box(6,74,27,17,"#fff",BLUE,"現有 AP（照明＋感測）",
    "802.11bf 排程 sounding\nCSI 在 AP 端抽取\n→ 天生均勻取樣",tsize=10.5)
box(37,74,26,17,"#fff",GREEN,"受試者 / 病床",
    "人在 AP–裝置連線附近\n呼吸→CSI 微幅週期擾動",tsize=10.5)
box(67,74,27,17,"#fff",SLATE,"現有裝置（反射端）",
    "電視 / IoT / 手機\n不外加專用硬體",tsize=10.5,tcol=SLATE)
arr(33,82.5,37,82.5,col=BLUE); arr(63,82.5,67,82.5,col=GREEN)
ax.text(50,72.7,"關鍵：不被動蹭流量（會爆發式）；改用排程 sounding（均勻取樣）",ha="center",fontsize=8.6,color=RED,style="italic")
box(20,51,60,15,"#fff",SLATE,"邊緣運算",
    "帶通 → PASS 選子載波 → 呼吸率/動作/事件偵測（雙任務模型）\n只上傳「特徵/事件」而非原始 CSI → 低頻寬、保護隱私",tsize=10.5,bsize=8.8)
box(8,30,40,14,"#fff",AMBER,"後端伺服器（院內）",
    "重模型/趨勢/AHI\nsite calibration 資料庫\nper-房間校準",tsize=10.5)
box(54,30,38,14,"#fff",AMBER,"整合 / 儲存",
    "警報引擎 → 護理站\nEMR/HIS 整合\n加密、稽核、on-prem",tsize=10.5)
box(20,8,60,13,"#fff",RED,"護理站儀表板 / 醫護",
    "即時 vitals、呼吸中止警報、夜間趨勢；異常才提示 → 減少警報疲勞",tsize=10.5,bsize=8.8)
arr(50,74,50,66.2)
arr(50,51,50,44.2,"特徵 / 事件（非原始資料）")
arr(40,30,40,21.2)
ax.add_patch(FancyArrowPatch((73,30),(73,24),arrowstyle="-",color=SLATE,lw=1.8))
ax.add_patch(FancyArrowPatch((73,24),(50.5,24),arrowstyle="-|>",mutation_scale=16,color=SLATE,lw=1.8))
fig.suptitle("目標部署架構（C）：善用現有 AP 做 802.11bf 感測 —— 不外加專用硬體",fontsize=15,weight="bold",y=0.975)
fig.text(0.5,0.02,"DofLab · 國立勤益科技大學 · 智慧自動化工程系",ha="center",fontsize=8.5,color=SLATE)
fig.savefig(os.path.join(OUT,"deploy_arch.png"),bbox_inches="tight",dpi=125); plt.close(fig)
print("wrote", os.path.join(OUT,"topo_options.png"), "and deploy_arch.png")
