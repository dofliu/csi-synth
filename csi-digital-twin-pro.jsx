import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, ResponsiveContainer,
  BarChart, Bar, ReferenceLine, ScatterChart, Scatter, ZAxis,
} from "recharts";

/* ============================================================
   WiFi CSI 數位孿生控制系統 · PRO  ·  DofLab
   真實化：MIMO 多天線 · 家具多路徑 · 二階反射 ·
           完整硬體損傷(CFO/SFO/AGC) · 複數 I/Q 軌跡
   物理：H = H_static(direct+walls+furniture) + H_person(t)
   ============================================================ */

// ── palette ──
const BG="#EEEDE9",PANEL="#FBFBFA",INK="#18191C",GRAY="#8B8F95",HAIR="#CFCFC9",
      SLATE="#5A6B7A",LINEN="#B8B0A4",RED="#8B2020",GREEN="#375623",AMBER="#C55A11";

// ── radio constants ──
const F0=2.437e9, BW=20e6, C=3e8, FS=20, HIST=80;
const DFT_WIN=FS*10;

// ── hardware presets ──
const HW={
  ax211:{ label:"Intel AX211", sub:256, ant:2, note:"Wi-Fi 6E · 2 天線" },
  ax210:{ label:"Intel AX210", sub:114, ant:2, note:"Wi-Fi 6 · 2 天線" },
  esp32:{ label:"ESP32-S3",    sub:56,  ant:1, note:"低成本 · 單天線" },
};

// ── spaces with furniture (metres) ──
const SPACES={
  bedroom:{label:"臥室",w:5,h:4,tx:[0.6,2.0],rx:[4.4,2.0],bed:[2.5,2.0],
    furn:[{x:0.6,y:0.5,r:0.30,n:"衣櫃"},{x:4.4,y:3.5,r:0.18,n:"床頭櫃"},{x:2.5,y:0.4,r:0.15,n:"窗"}]},
  living:{label:"客廳",w:6,h:5,tx:[0.8,2.5],rx:[5.2,2.5],bed:[3.0,2.5],
    furn:[{x:1.0,y:4.4,r:0.28,n:"沙發"},{x:5.5,y:2.5,r:0.22,n:"電視"},{x:3.0,y:1.0,r:0.16,n:"茶几"}]},
  ward:{label:"病房",w:4,h:3,tx:[0.5,1.5],rx:[3.5,1.5],bed:[2.0,1.5],
    furn:[{x:0.5,y:0.5,r:0.22,n:"儀器"},{x:3.5,y:0.5,r:0.16,n:"櫃"}]},
  car:{label:"車內",w:3,h:2,tx:[0.4,1.0],rx:[2.6,1.0],bed:[1.5,1.0],
    furn:[{x:1.5,y:0.3,r:0.20,n:"儀表板"},{x:0.3,y:1.0,r:0.14,n:"門"},{x:2.7,y:1.0,r:0.14,n:"門"}]},
};
const TASKS={
  empty:{label:"空間淨空",desc:"無人環境基線"},
  breathe:{label:"靜止呼吸",desc:"仰臥呼吸(+可選心跳)"},
  walk:{label:"走路移動",desc:"沿路徑往返"},
  posture:{label:"睡眠翻身",desc:"週期姿態轉換"},
  apnea:{label:"呼吸中止",desc:"呼吸→憋氣交替"},
};
// ── clinical apnea sub-types (Stage-2) ──
const APNEA_TYPES={
  csa:{label:"中樞型 CSA", desc:"動作完全停止", note:"胸腹皆停 → 動作型偵測可抓到"},
  osa:{label:"阻塞型 OSA", desc:"動作持續、氣流阻塞", note:"胸腹矛盾運動、動作仍在 → 動作型偵測會漏判"},
  hypo:{label:"低通氣", desc:"呼吸變淺(非停止)", note:"振幅部分降低 → 常被漏偵"},
};
// ── realism (impairment) levels ──
const REALISM={
  clean:{label:"乾淨",snr:45,cfo:0,sfo:0,agc:0,jit:0},
  std:{label:"標準",snr:30,cfo:200,sfo:5,agc:0.03,jit:0.02},
  harsh:{label:"嚴苛",snr:16,cfo:500,sfo:10,agc:0.06,jit:0.05},
};
// ── failure / interference scenarios ──
const INTERF={
  none:  { label:"無干擾", desc:"理想條件" },
  twoppl:{ label:"兩人同床", desc:"兩組呼吸混疊（單鏈路多鎖定較強者，需多天線分離）" },
  walker:{ label:"旁人走動", desc:"移動淹沒微弱呼吸" },
  emi:   { label:"電磁干擾", desc:"微波爐/變頻器拉高雜訊" },
  faraway:{label:"距離過遠", desc:"人偏離主路徑，訊號過弱" },
  fan:   { label:"風扇干擾", desc:"非人體週期源誤判" },
  pet:   { label:"寵物移動", desc:"小型移動散射體間歇擾動" },
  hvac:  { label:"空調週期", desc:"冷氣壓縮機約 0.2Hz 週期起伏" },
  cochan:{ label:"同頻/流量", desc:"共享頻道流量→採樣不穩、突發遺失" },
  plmd:  { label:"週期性肢動", desc:"睡眠肢體抽動(PLMD)約每 20–40s 一次" },
};
// ── wall / boundary material: reflection coefficient scaling ──
const WALL_MAT={
  drywall: { label:"乾牆",     refl:1.00, note:"標準石膏板" },
  concrete:{ label:"混凝土",   refl:1.55, note:"強反射、長回音、指紋更陡" },
  glass:   { label:"玻璃/磁磚", refl:1.30, note:"鏡面反射、相位穩定" },
  wood:    { label:"木質",     refl:0.70, note:"部分吸收、弱反射" },
};
// ── sleep stages (overnight mode): rate, cycle-variability, apnea propensity ──
const STAGES={
  wake:{label:"清醒", bpm:16, varr:0.12, apneaW:0.0, col:GRAY},
  n1:  {label:"N1 淺睡", bpm:15, varr:0.09, apneaW:0.4, col:SLATE},
  n2:  {label:"N2",     bpm:14, varr:0.06, apneaW:0.6, col:SLATE},
  n3:  {label:"N3 深睡", bpm:13, varr:0.04, apneaW:0.2, col:GREEN},
  rem: {label:"REM",    bpm:17, varr:0.16, apneaW:1.0, col:AMBER},
};
// compressed hypnogram: [stageKey, minutesOfNight] — one ~7.5h night
const HYPNO=[
  ["wake",8],["n1",6],["n2",22],["n3",28],["n2",14],["rem",18],
  ["n2",20],["n3",16],["n2",18],["rem",26],["n1",6],["n2",22],
  ["rem",30],["wake",6],["n2",14],["rem",22],["wake",6],
];
const NIGHT_MIN=HYPNO.reduce((a,s)=>a+s[1],0);   // total simulated minutes
const NIGHT_SECS=90;                             // real seconds to play a full night
// ── acquisition-defect presets (real CSI is NOT uniformly sampled) ──
const ACQ={
  loss:0.08,      // baseline packet-loss probability per frame
  tsJit:0.35,     // timestamp jitter as fraction of nominal 1/FS
  calAmp:0.18,    // per-subcarrier fixed amplitude calibration spread (σ)
  sto:0.9,        // sampling-time-offset → random per-packet phase ramp (rad across band)
};
// ── build one overnight event schedule from the hypnogram (deterministic) ──
// returns per-minute stage timeline, apnea/hypopnea events, true AHI and a
// MOTION-DETECTOR AHI (deliberately under-counts OSA/hypopnea → clinical C4 point)
function buildNight(){
  const timeline=[]; for(const [stg,dur] of HYPNO){ for(let i=0;i<dur;i++) timeline.push(stg); }
  const total=timeline.length, events=[];
  for(let mi=0;mi<total;mi++){
    const w=STAGES[timeline[mi]].apneaW; if(w<=0) continue;
    if(seeded(mi,3) < 0.13*w){
      const r=seeded(mi,5), type=r<0.55?"osa":r<0.8?"hypo":"csa";
      events.push({atMin:mi, dur:0.25+0.35*seeded(mi,9), type, stage:timeline[mi]});
    }
  }
  const hours=total/60;
  const by={osa:0,csa:0,hypo:0}; let det=0;
  for(const e of events){ by[e.type]++; det += e.type==="csa"?1 : e.type==="osa"?0.15 : 0.05; }
  return { timeline, total, events, by,
    ahiTruth:+(events.length/hours).toFixed(1),
    ahiMotion:+(det/hours).toFixed(1) };
}

// ── antenna positions: n antennas offset ⟂ to Tx→Rx, spaced ~6cm ──
function rxAntennas(rx,tx,n){
  if(n<=1) return [rx];
  const dx=rx[0]-tx[0], dy=rx[1]-tx[1], L=Math.hypot(dx,dy)||1;
  const nx=-dy/L, ny=dx/L, s=0.06;               // λ/2 @2.4GHz ≈ 6cm
  const out=[];
  for(let i=0;i<n;i++){ const o=(i-(n-1)/2)*s; out.push([rx[0]+nx*o, rx[1]+ny*o]); }
  return out;
}

// ── image sources: 1st + 2nd order (corners), scaled by wall-material reflectivity ──
function wallImages(tx,W,H,refl){
  const [x,y]=tx; const m=refl===undefined?1:refl;
  return [
    {p:[-x,y],a:0.36*m},{p:[2*W-x,y],a:0.36*m},{p:[x,-y],a:0.30*m},{p:[x,2*H-y],a:0.30*m}, // 1st
    {p:[-x,-y],a:0.16*m*m},{p:[2*W-x,-y],a:0.16*m*m},{p:[-x,2*H-y],a:0.14*m*m},{p:[2*W-x,2*H-y],a:0.14*m*m}, // 2nd (corners)
  ];
}
const dist=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
// ── deterministic hash-based RNG (stable per-config calibration, not per-frame noise) ──
function seeded(i,salt){ let x=Math.sin((i+1)*12.9898+(salt||0)*78.233)*43758.5453; return x-Math.floor(x); }
// ── seedable stream PRNG (mulberry32): every stochastic term (AWGN/CFO jitter/diffuse/
//    AGC/packet-loss/STO) is drawn from this, so a whole synthetic capture is byte-repro-
//    ducible from (seed + config). This is what lets a sim run be regenerated and aligned
//    frame-by-frame against a real AX211 capture recorded under matched conditions. ──
function mulberry32(seed){ let a=seed>>>0; return function(){ a|=0; a=(a+0x6D2B79F5)|0;
  let t=Math.imul(a^(a>>>15),1|a); t=(t+Math.imul(t^(t>>>7),61|t))^t; return ((t^(t>>>14))>>>0)/4294967296; }; }
// ── OFDM subcarrier structure: real 802.11 CSI is NOT usable on every tone — the DC
//    subcarrier is nulled and the band edges are guard bands (no energy / unreliable CSI).
//    Intel AX211 delivers this structure; masking it here makes the exported CSI and the
//    heatmap match what a real capture actually contains. 1=usable, 0=null/guard. ──
function ofdmMask(nSub){ const m=new Uint8Array(nSub); m.fill(1);
  const guard=Math.max(2,Math.round(nSub*0.045));
  for(let k=0;k<guard;k++){ m[k]=0; m[nSub-1-k]=0; }
  m[Math.floor(nSub/2)]=0;                       // null DC subcarrier
  return m; }
// per-subcarrier fixed amplitude calibration offsets (Intel CSI has these; stable per capture)
function makeCalib(nSub,spread){ const c=new Float64Array(nSub);
  for(let k=0;k<nSub;k++) c[k]=1+(seeded(k,7)*2-1)*spread; return c; }
// 3D ground-reflection path length: Tx & Rx at height ~1.0m, floor bounce adds vertical detour
function floorPathLen(dHoriz){ const h=1.0; return Math.hypot(dHoriz, 2*h); }

// ── STATIC channel: direct + walls(material) + furniture + floor bounce (config-change only) ──
function computeStatic(tx,rxA,furn,W,H,freqs,useFurn,refl,useGround){
  const dD=dist(tx,rxA);
  const imgs=wallImages(tx,W,H,refl);
  const dFloor=floorPathLen(dD);            // 3D ground-reflection detour
  const re=new Float64Array(freqs.length), im=new Float64Array(freqs.length);
  for(let k=0;k<freqs.length;k++){
    const lam=C/freqs[k], ph=d=>2*Math.PI*d/lam;
    let r=0,i=0;
    const ad=1/(dD+0.1); r+=ad*Math.cos(ph(dD)); i-=ad*Math.sin(ph(dD));
    for(const w of imgs){ const d=dist(w.p,rxA), a=w.a/(d+0.1); r+=a*Math.cos(ph(d)); i-=a*Math.sin(ph(d)); }
    if(useFurn) for(const f of furn){ const d=dist(tx,[f.x,f.y])+dist([f.x,f.y],rxA), a=f.r/(d+0.1);
      r+=a*Math.cos(ph(d)); i-=a*Math.sin(ph(d)); }
    if(useGround){ const a=0.45*(refl===undefined?1:refl)/(dFloor+0.1); r+=a*Math.cos(ph(dFloor)); i-=a*Math.sin(ph(dFloor)); }
    re[k]=r; im[k]=i;
  }
  return {re,im};
}
// ── DYNAMIC person scatter (recomputed each frame) ──
// realistic (non-sinusoidal, slightly variable) respiration displacement, deterministic
function realBreath(t,bpm,ampM){
  const f=(bpm/60);
  // slow rate + amplitude variability (cycle-to-cycle)
  const ph=2*Math.PI*f*t + 0.35*Math.sin(2*Math.PI*0.05*t);
  const shape=Math.sin(ph)+0.18*Math.sin(2*ph);   // asymmetric inhale/exhale
  const ampMod=1+0.12*Math.sin(2*Math.PI*0.03*t+1.3);
  return ampM*ampMod*shape;
}
// cardiac micro-motion: a SEPARATE spectral band from respiration (~1.0–1.3 Hz) with
// heart-rate variability, so the breathing-band and cardiac-band peaks are distinguishable
// (this is what a dual-band respiration+heartbeat estimator must separate on real data).
function realHeart(t,hrBpm,ampM){
  const f=(hrBpm/60)*(1+0.045*Math.sin(2*Math.PI*0.1*t)+0.02*Math.sin(2*Math.PI*0.25*t));
  return ampM*(Math.sin(2*Math.PI*f*t)+0.30*Math.sin(4*Math.PI*f*t));
}

// ── multipath propagation (for the propagation view) ──
const PROP_EMIT=48, PROP_SPEED=0.13;   // frames between emissions; metres per frame
function computePropPaths(T,R,W,H){
  const d=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]); const paths=[{pts:[T,R],len:d(T,R),type:"direct"}];
  const walls=[[[0,0],[W,0]],[[W,0],[W,H]],[[W,H],[0,H]],[[0,H],[0,0]]];
  for(const [a,b] of walls){ const ab=[b[0]-a[0],b[1]-a[1]];
    const tt=((T[0]-a[0])*ab[0]+(T[1]-a[1])*ab[1])/(ab[0]*ab[0]+ab[1]*ab[1]);
    const f=[a[0]+tt*ab[0],a[1]+tt*ab[1]], img=[2*f[0]-T[0],2*f[1]-T[1]];
    const d1=[R[0]-img[0],R[1]-img[1]], den=d1[0]*ab[1]-d1[1]*ab[0]; if(Math.abs(den)<1e-9) continue;
    const tp=((a[0]-img[0])*ab[1]-(a[1]-img[1])*ab[0])/den, u=((a[0]-img[0])*d1[1]-(a[1]-img[1])*d1[0])/den;
    if(u<0||u>1||tp<=0) continue; const P=[img[0]+tp*d1[0],img[1]+tp*d1[1]];
    paths.push({pts:[T,P,R],len:d(T,P)+d(P,R),type:"reflect"}); }
  return paths;
}
function posAlong(pts,trav){ let acc=0; for(let i=0;i<pts.length-1;i++){ const a=pts[i],b=pts[i+1],d=Math.hypot(b[0]-a[0],b[1]-a[1]);
  if(trav<=acc+d){ const fr=(trav-acc)/d; return [a[0]+fr*(b[0]-a[0]),a[1]+fr*(b[1]-a[1])]; } acc+=d; } return null; }

function computePerson(tx,rxA,px,py,extra,freqs,scale){
  const sc = scale===undefined?1:scale;
  const bx=rxA[0]-tx[0], by=rxA[1]-tx[1], l2=bx*bx+by*by;
  const t=Math.max(0,Math.min(1,((px-tx[0])*bx+(py-tx[1])*by)/l2));
  const dl=Math.hypot(px-(tx[0]+t*bx),py-(tx[1]+t*by));
  const sig=Math.exp(-dl/0.85);
  const dS=dist(tx,[px,py])+dist([px,py],rxA)+extra;
  const re=new Float64Array(freqs.length), im=new Float64Array(freqs.length);
  for(let k=0;k<freqs.length;k++){
    const lam=C/freqs[k], a=0.5*sig*sc/(dS+0.1), p=2*Math.PI*dS/lam;
    re[k]=a*Math.cos(p); im[k]=-a*Math.sin(p);
  }
  return {re,im,sig};
}

// ── DFT band (0.025 Hz resolution) ──
function dftBand(sig,fs,lo,hi){
  const N=sig.length; if(N<20)return{peakHz:null,peakMag:0,total:0,spec:[]};
  const mu=sig.reduce((s,v)=>s+v,0)/N, x=sig.map(v=>v-mu);
  const spec=[]; let peakHz=null,peakMag=0,total=0;
  for(let fi=1;fi<=54;fi++){ const f=fi*0.025; if(f>1.4)break; let re=0,im=0;
    for(let n=0;n<N;n++){const a=2*Math.PI*f/fs*n; re+=x[n]*Math.cos(a); im-=x[n]*Math.sin(a);}
    const mag=Math.hypot(re,im)/N; spec.push({freq:+f.toFixed(3),mag:+mag.toFixed(5)}); total+=mag;
    if(f>=lo&&f<=hi&&mag>peakMag){peakMag=mag;peakHz=f;}}
  return {peakHz,peakMag,total,spec};
}

// estimate breathing BPM by fusing a given set of subcarriers' breathing-band spectra
function bpmFromSubs(buf, subs, key){
  if(!buf.length||!subs||!subs.length) return null;
  const N=buf.length;
  const cols=subs.map(k=>{const c=buf.map(f=>f.sub[k]); const m=c.reduce((a,v)=>a+v,0)/c.length; return c.map(v=>v-m);});
  let bestF=null,bestMag=-1;
  for(let fi=6;fi<=24;fi++){ const f=fi*0.025; let mag=0;
    for(const c of cols){ let re=0,im=0; for(let n=0;n<N;n++){const a=2*Math.PI*f/FS*n; re+=c[n]*Math.cos(a); im-=c[n]*Math.sin(a);} mag+=Math.hypot(re,im)/N; }
    mag/=cols.length; if(mag>bestMag){bestMag=mag;bestF=f;}
  }
  return bestF?Math.round(bestF*60):null;
}
// learn the top-K most breathing-sensitive subcarriers for the CURRENT room
function learnProfile(buf, nSub, K){
  if(!buf.length) return null;
  const N=buf.length, en=new Float64Array(nSub);
  for(let k=0;k<nSub;k++){ const c=buf.map(f=>f.sub[k]); const m=c.reduce((a,v)=>a+v,0)/c.length; const x=c.map(v=>v-m);
    for(let fi=6;fi<=24;fi++){ const f=fi*0.025; let re=0,im=0; for(let n=0;n<N;n++){const a=2*Math.PI*f/FS*n; re+=x[n]*Math.cos(a); im-=x[n]*Math.sin(a);} en[k]+=Math.hypot(re,im)/N; }
  }
  return Array.from(en.keys()).sort((a,b)=>en[b]-en[a]).slice(0,K);
}

function drawHeat(cv,hist,nSub){
  if(!cv||!hist.length)return;
  const ctx=cv.getContext("2d"),W=cv.width,H=cv.height,cW=W/nSub,cH=H/HIST,hi=Math.max(...hist.flat(),0.01);
  hist.forEach((f,row)=>f.forEach((v,col)=>{const t=Math.min(1,v/(hi*0.75));
    ctx.fillStyle=`rgb(${Math.round(238-148*t)},${Math.round(237-130*t)},${Math.round(233-111*t)})`;
    ctx.fillRect(col*cW,row*cH,cW+0.5,cH+0.5);}));
}

export default function CSIDigitalTwinPro(){
  // config
  const [hw,setHw]=useState("ax211");
  const [space,setSpace]=useState("bedroom");
  const [task,setTask]=useState("breathe");
  const [brSet,setBrSet]=useState(15);
  const [heart,setHeart]=useState(false);
  const [realism,setRealism]=useState("std");
  const [physReal,setPhysReal]=useState(false);
  const [apneaType,setApneaType]=useState("csa");
  const [interf,setInterf]=useState("none");
  const [useFurn,setUseFurn]=useState(true);
  const [antView,setAntView]=useState(0);
  const [running,setRunning]=useState(false);
  // ── new realism controls ──
  const [wallMat,setWallMat]=useState("drywall");   // boundary material
  const [useGround,setUseGround]=useState(false);    // 3D floor bounce
  const [thermal,setThermal]=useState(false);        // slow environmental (thermal) drift
  const [acqReal,setAcqReal]=useState(false);        // real CSI acquisition defects
  const [night,setNight]=useState(false);            // overnight time-compressed mode
  const [seed,setSeed]=useState(12345);              // PRNG seed → reproducible capture
  const [ofdmStruct,setOfdmStruct]=useState(false);  // AX211 null/guard subcarrier structure
  const [blanket,setBlanket]=useState(false);        // 棉被遮蔽 → weaker person scatter
  const [nightState,setNightState]=useState({stage:"wake",clockMin:0,ahi:0,events:0,lossPct:0});
  const [nightLog,setNightLog]=useState([]);         // {min,stage,type} apnea/hypopnea events
  const [valid,setValid]=useState(null);             // {mae,n,acc,tot,loss}
  const [copied,setCopied]=useState(false);          // export-to-clipboard feedback

  const sp=SPACES[space], hwc=HW[hw];
  const N_SUB=hwc.sub, N_ANT=hwc.ant;
  const freqsRef=useRef([]);
  useEffect(()=>{ freqsRef.current=Array.from({length:N_SUB},(_,k)=>F0+(k-N_SUB/2+0.5)*(BW/N_SUB)); },[N_SUB]);

  const [tx,setTx]=useState(sp.tx);
  const [rx,setRx]=useState(sp.rx);
  const [person,setPerson]=useState({px:sp.bed[0],py:sp.bed[1]});
  const [drag,setDrag]=useState(null);

  const [rip,setRip]=useState(0);
  const [showProp,setShowProp]=useState(false);
  const [propStats,setPropStats]=useState({tx:0,rx:0});
  const pulsesRef=useRef([]), txCount=useRef(0), rxCount=useRef(0), propPathsRef=useRef([]);
  const [hist,setHist]=useState(()=>Array.from({length:HIST},()=>new Array(N_SUB).fill(0.5)));
  const [series,setSeries]=useState([]);
  const [iq,setIq]=useState([]);
  const [det,setDet]=useState({label:"未啟動",conf:0,bpm:null,spec:[]});
  const [metrics,setMetrics]=useState({snr:0,paths:0});
  const [iMark,setIMark]=useState([]);
  // ── site calibration (before/after training) ──
  const [calibrated,setCalibrated]=useState(false);
  const [calibrating,setCalibrating]=useState(false);
  const [calibComp,setCalibComp]=useState(null);   // {genericBPM, calibBPM, truth}
  const calibProfileRef=useRef(null);              // learned best subcarriers for this room

  const R=useRef({}); R.current={hw,space,task,brSet,heart,realism,physReal,apneaType,interf,useFurn,running,tx,rx,person,antView,N_SUB,N_ANT,showProp,wallMat,useGround,thermal,acqReal,night,seed,ofdmStruct,blanket};
  const staticRef=useRef([]);   // per-antenna static channel
  const agcRef=useRef(0);
  const calibRef=useRef(null);  // per-subcarrier fixed amplitude calibration vector
  const stoRef=useRef(0);       // current sampling-time-offset phase ramp (per packet)
  const rngRef=useRef(mulberry32(12345));  // seedable per-frame stochastic stream
  const ofdmRef=useRef(null);   // OFDM usable-subcarrier mask (null/guard tones)
  const csiExpRef=useRef([]);   // ring buffer of complex CSI (view antenna) for export
  const nightRef=useRef({t0:0,events:[],lastEvt:-999,lastLog:0}); // overnight accumulator
  const validRef=useRef({sum:0,n:0,ok:0,tot:0}); // validation accumulator (truth vs est)
  const lossRef=useRef({drop:0,pkt:0});          // packet-loss accounting
  const bufRef=useRef([]); const tRef=useRef(0);
  const svgRef=useRef(null),cvRef=useRef(null),animRef=useRef(null),fN=useRef(0),breathSeen=useRef(-999);

  // recompute static channel when geometry/config changes
  const recomputeStatic=useCallback(()=>{
    const s=SPACES[R.current.space], f=freqsRef.current;
    if(!f.length)return;
    const ants=rxAntennas(R.current.rx,R.current.tx,R.current.N_ANT);
    const refl=WALL_MAT[R.current.wallMat].refl;
    staticRef.current=ants.map(a=>computeStatic(R.current.tx,a,s.furn,s.w,s.h,f,R.current.useFurn,refl,R.current.useGround));
  },[]);
  useEffect(()=>{ recomputeStatic(); },[tx,rx,space,hw,useFurn,N_SUB,wallMat,useGround]);
  // regenerate per-subcarrier calibration vector when hardware (N_SUB) changes
  useEffect(()=>{ calibRef.current=makeCalib(N_SUB,ACQ.calAmp); },[N_SUB]);
  // rebuild OFDM usable-subcarrier mask when hardware (N_SUB) changes
  useEffect(()=>{ ofdmRef.current=ofdmMask(N_SUB); },[N_SUB]);
  // reseed the stochastic stream whenever the seed changes (reproducibility control)
  useEffect(()=>{ rngRef.current=mulberry32(seed>>>0); },[seed]);
  // material/ground/thermal change invalidates site calibration too
  useEffect(()=>{ setCalibrated(false); calibProfileRef.current=null; setCalibComp(null); },[wallMat,useGround]);

  // reset on space change
  useEffect(()=>{ const s=SPACES[space]; setTx(s.tx); setRx(s.rx); setPerson({px:s.bed[0],py:s.bed[1]});
    bufRef.current=[]; setSeries([]); setIq([]); setDet({label:"未啟動",conf:0,bpm:null,spec:[]}); breathSeen.current=-999;
  },[space]);
  useEffect(()=>{ if(antView>=N_ANT)setAntView(0); },[hw,N_ANT,antView]);
  // room/hardware change invalidates calibration (fragility to fingerprint change)
  useEffect(()=>{ setCalibrated(false); calibProfileRef.current=null; setCalibComp(null); },[space,hw,useFurn]);
  useEffect(()=>{ pulsesRef.current=[]; txCount.current=0; rxCount.current=0; setPropStats({tx:0,rx:0}); },[space,showProp]);
  useEffect(()=>{ bufRef.current=[]; setSeries([]); setIq([]); breathSeen.current=-999; },[task,hw]);
  useEffect(()=>{ if(interf==="none")setIMark([]); bufRef.current=[]; breathSeen.current=-999; },[interf]);
  useEffect(()=>{ setHist(Array.from({length:HIST},()=>new Array(N_SUB).fill(0.5))); },[N_SUB]);
  // reset validation + packet-loss accumulators whenever the scenario changes
  useEffect(()=>{ validRef.current={sum:0,n:0,ok:0,tot:0}; lossRef.current={drop:0,pkt:0}; setValid(null);
    csiExpRef.current=[]; rngRef.current=mulberry32(seed>>>0);
  },[task,space,interf,realism,physReal,acqReal,night,brSet,wallMat,useGround,thermal,hw,ofdmStruct,blanket,seed]);
  // (re)build the overnight schedule when entering night mode
  useEffect(()=>{ if(night){ nightRef.current.data=buildNight(); setNightLog(nightRef.current.data.events);
      tRef.current=0; bufRef.current=[]; breathSeen.current=-999; } else setNightLog([]); },[night]);

  // animation
  useEffect(()=>{
    const loop=()=>{
      fN.current++; setRip(r=>(r+1)%120);
      const st=R.current, f=freqsRef.current;
      // ── propagation view: emit pulses, count Tx emissions and Rx arrivals ──
      if(st.showProp && st.running){
        const pp=propPathsRef.current;
        if(pp.length){
          if(fN.current % PROP_EMIT===0){ pulsesRef.current.push({f0:fN.current,done:pp.map(()=>false)}); txCount.current++; }
          const maxLen=Math.max(0.1,...pp.map(p=>p.len));
          pulsesRef.current.forEach(pl=>{ const trav=(fN.current-pl.f0)*PROP_SPEED;
            pp.forEach((p,i)=>{ if(!pl.done[i] && trav>=p.len){ pl.done[i]=true; rxCount.current++; } }); });
          pulsesRef.current=pulsesRef.current.filter(pl=>(fN.current-pl.f0)*PROP_SPEED < maxLen+0.6);
          if(fN.current%6===0) setPropStats({tx:txCount.current,rx:rxCount.current});
        }
      }
      if(st.running && f.length && staticRef.current.length && fN.current%3===0){
        tRef.current+=1/FS; const t=tRef.current; const s=SPACES[st.space];
        const rng=rngRef.current;                      // seeded stochastic stream (reproducible)
        let px=st.person.px, py=st.person.py, present=true, extra=0;
        const rl=REALISM[st.realism];
        let nightCur=null, effBpm=st.brSet, truthLabel="";

        if(st.night){
          // ── overnight time-compressed mode: hypnogram drives rate/variability + scheduled events ──
          const nd=nightRef.current.data || (nightRef.current.data=buildNight());
          const frac=Math.min(1, tRef.current/NIGHT_SECS), clockMin=frac*NIGHT_MIN;
          const mi=Math.min(nd.total-1, Math.floor(clockMin)), stg=nd.timeline[mi], sc=STAGES[stg];
          effBpm=sc.bpm;
          let ev=null; for(const e of nd.events){ if(clockMin>=e.atMin && clockMin<e.atMin+e.dur){ ev=e; break; } }
          const br=2*realBreath(t,sc.bpm,0.006*(1+sc.varr));
          if(ev){
            if(ev.type==="csa"){ const p=(clockMin-ev.atMin)/ev.dur; const env=Math.max(0,Math.sin(Math.PI*p)); extra=br*env*env; } // Cheyne-Stokes wax→wane→apnea
            else if(ev.type==="hypo") extra=br*0.35;
            else extra=br*1.15;                        // OSA: effort persists
            truthLabel="event";
          } else { extra=br; truthLabel=stg==="wake"?"wake":"breathe"; }
          // posture shifts across the night
          const off=[[0,0],[-0.18,0.05],[0.18,0.05],[0,-0.12],[0.10,-0.06]][mi%5];
          px=s.bed[0]+off[0]; py=s.bed[1]+off[1];
          nightCur={clockMin,stg,ev,nd};
        }
        else if(st.task==="empty"){ present=false; truthLabel="empty"; }
        else if(st.task==="breathe"){ truthLabel="breathe";
          extra = st.physReal ? 2*realBreath(t,st.brSet,0.006) : 2*0.006*Math.sin(2*Math.PI*(st.brSet/60)*t);
          if(st.heart) extra+=2*realHeart(t,72,0.0015);
        }
        else if(st.task==="walk"){ truthLabel="walk"; const cyc=t%10,W=s.w,mx=0.6;
          px=cyc<5?mx+(cyc/5)*(W-2*mx):(W-mx)-((cyc-5)/5)*(W-2*mx); py=s.bed[1]+Math.sin(t*1.1)*0.4; }
        else if(st.task==="posture"){ truthLabel="breathe"; const seg=Math.floor(t/8)%4, off=[[0,0],[-0.15,0.05],[0.15,0.05],[0,-0.1]][seg];
          px=s.bed[0]+off[0]; py=s.bed[1]+off[1];
          extra = st.physReal ? 2*realBreath(t,st.brSet,0.006) : 2*0.006*Math.sin(2*Math.PI*(st.brSet/60)*t);
          if(st.heart) extra+=2*realHeart(t,72,0.0015); }
        else if(st.task==="apnea"){ truthLabel="apnea"; const hold=(t%30)>=15&&(t%30)<25;
          const br = st.physReal ? 2*realBreath(t,st.brSet,0.006) : 2*0.006*Math.sin(2*Math.PI*(st.brSet/60)*t);
          if(!hold){ extra=br; }
          else if(st.apneaType==="csa"){ extra=0; }                 // effort stops
          else if(st.apneaType==="hypo"){ extra=br*0.35; }          // partial reduction
          else if(st.apneaType==="osa"){ extra=br*1.15; }           // effort continues/intensifies
        }

        // ── interference / failure sources (disabled during overnight mode) ──
        const iType=st.night?"none":st.interf;
        let interfScat=[];        // extra scatterers [{px,py,extra}]
        let snrEff=rl.snr;        // effective SNR (EMI/HVAC lowers it)
        let personScale=1;        // person scatter attenuation (faraway)
        let lossBoost=0;          // extra packet-loss from shared-channel traffic (cochan)
        if(iType==="twoppl"){
          const e2=2*0.006*Math.sin(2*Math.PI*((st.brSet+5)/60)*t+1.1);
          interfScat.push({px:s.bed[0]+0.35,py:s.bed[1]+0.25,extra:e2});
          if(present) { px=s.bed[0]-0.3; py=s.bed[1]-0.15; }
        } else if(iType==="walker"){
          // intermittent passer-by crossing ON the Tx-Rx line (max disruption) 5s / 9s
          if((t%14)<5){ const c=t%5, wx=0.9+(c/5)*(s.w-1.8);
            interfScat.push({px:wx,py:s.bed[1],extra:0}); }
        } else if(iType==="emi"){
          snrEff = 6;                                  // steady low SNR (variable-freq drive)
        } else if(iType==="faraway"){
          if(present){ px=s.w-0.4; py=Math.max(0.35,s.h-0.4); personScale=0.4; }
        } else if(iType==="fan"){
          const ef=2*0.02*Math.sin(2*Math.PI*0.7*t);
          interfScat.push({px:s.w-0.4,py:s.h-0.4,extra:ef});
        } else if(iType==="pet"){
          // small mobile scatterer wandering intermittently near the floor
          if((t%11)<4){ const wx=1.0+0.8*Math.sin(t*1.7), wy=s.h-0.6-0.3*Math.cos(t*1.3);
            interfScat.push({px:Math.max(0.3,Math.min(s.w-0.3,wx)),py:Math.max(0.3,Math.min(s.h-0.3,wy)),extra:0.04*Math.sin(t*4)}); }
        } else if(iType==="hvac"){
          // compressor cycles ~0.02Hz: broadband SNR breathing + a ~0.2Hz reflector
          snrEff = rl.snr - 8*(0.5+0.5*Math.sin(2*Math.PI*0.02*t));
          interfScat.push({px:0.6,py:0.6,extra:0.03*Math.sin(2*Math.PI*0.2*t)});
        } else if(iType==="cochan"){
          // shared-channel traffic: bursty packet loss + sampling instability
          lossBoost = ((t%6)<2)?0.5:0.05;
        } else if(iType==="plmd"){
          // periodic limb movement: brief limb twitch every ~30s (0.033 Hz), a
          // transient non-respiratory scatterer that can be mistaken for motion
          if((t%30)<1.2){ interfScat.push({px:s.bed[0]+0.35,py:s.bed[1]+0.30,extra:0.05*Math.sin(t*9)}); }
        }
        // 棉被遮蔽: dielectric cover attenuates the through-body scatter path
        if(st.blanket) personScale*=0.55;
        // expose interference markers for rendering (throttled)
        if(fN.current%3===0){
          const marks=interfScat.map(sc=>({x:sc.px,y:sc.py,
            label: iType==="twoppl"?"人2": iType==="walker"?"路人": iType==="fan"?"風扇": iType==="pet"?"寵物": iType==="hvac"?"空調": iType==="plmd"?"肢動":"?"}));
          if(iType==="faraway"&&present) marks.push({x:px,y:py,label:"遠"});
          setIMark(marks);
        }

        // ── physics realism: extended body (abdomen) + background micro-motion ──
        let realScat=[];
        if(st.physReal && present){
          // abdomen: offset from thorax, phase-shifted breathing (thoraco-abdominal)
          const abd = 2*realBreath(t-0.4,st.brSet,0.006)*0.85;
          realScat.push({px:px, py:py+0.12, extra:abd, sc:0.7});
        }
        if(st.physReal){
          // background micro-motion: slow-drifting environmental reflectors
          realScat.push({px:0.5, py:s.h-0.5, extra:0.03*Math.sin(2*Math.PI*0.04*t), sc:0.4});
          realScat.push({px:s.w-0.6, py:0.6, extra:0.03*Math.sin(2*Math.PI*0.06*t+2), sc:0.35});
        }

        // AGC slow drift update
        agcRef.current += (rng()*2-1)*rl.agc*0.05;
        agcRef.current *= 0.995;
        const gain = 1 + Math.tanh(agcRef.current);

        // per-packet acquisition/thermal terms
        const stoRamp = st.acqReal ? (rng()*2-1)*ACQ.sto : 0;   // sampling-time-offset phase ramp
        const thScale = st.thermal ? (1+0.06*Math.sin(2*Math.PI*t/40)) : 1; // slow environmental gain drift
        const thPh    = st.thermal ? 0.18*Math.sin(2*Math.PI*t/55) : 0;     // slow environmental phase drift
        const cal     = calibRef.current;
        const omask   = st.ofdmStruct ? ofdmRef.current : null;   // null/guard subcarrier mask
        // per-antenna complex CSI = static + person, then impairments
        const perAntAmp=[]; let sampleRe=0,sampleIm=0;
        const expRe=new Float64Array(N_SUB), expIm=new Float64Array(N_SUB);   // view-antenna complex CSI (export)
        const viewK=Math.floor(N_SUB/2);
        for(let ai=0; ai<st.N_ANT; ai++){
          const stat=staticRef.current[ai];
          const ants=rxAntennas(st.rx,st.tx,st.N_ANT);
          const pers= present ? computePerson(st.tx,ants[ai],px,py,extra,f,personScale) : null;
          // interference scatterers for this antenna
          const iScat=interfScat.map(s2=>computePerson(st.tx,ants[ai],s2.px,s2.py,s2.extra,f));
          // physics-realism scatterers (abdomen, background) for this antenna
          const rScat=realScat.map(s2=>{const r=computePerson(st.tx,ants[ai],s2.px,s2.py,s2.extra,f);
            return {re:r.re,im:r.im,sc:s2.sc};});
          const amp=new Float64Array(N_SUB);
          // impairment phase terms
          const cfoP=2*Math.PI*rl.cfo*t;
          const jit=(rng()*2-1)*rl.jit;
          // Rician diffuse weights (physReal): split specular vs diffuse (K=8 dB)
          const Klin=Math.pow(10,8/10), wSpec=Math.sqrt(Klin/(Klin+1)), wDiff=Math.sqrt(1/(Klin+1));
          for(let k=0;k<N_SUB;k++){
            let re=stat.re[k]*thScale, im=stat.im[k]*thScale;   // thermal slow gain drift on static
            if(pers){ re+=pers.re[k]; im+=pers.im[k]; }
            for(const isc of iScat){ re+=isc.re[k]; im+=isc.im[k]; }
            for(const rsc of rScat){ re+=rsc.re[k]*rsc.sc; im+=rsc.im[k]*rsc.sc; }
            if(st.physReal){ // diffuse: specular attenuation + temporally-varying diffuse term
              const amp0=Math.hypot(re,im);
              re=re*wSpec+(rng()*2-1)*wDiff*amp0*0.7;
              im=im*wSpec+(rng()*2-1)*wDiff*amp0*0.7;
            }
            // SFO: phase slope across subcarriers growing with time; +STO per-packet ramp; +thermal phase
            const sfoP=2*Math.PI*(rl.sfo*1e-6)*(k-N_SUB/2)*t*0.5;
            const stoP=stoRamp*(k-N_SUB/2)/N_SUB;
            const rot=cfoP+sfoP+jit+stoP+thPh;
            const cr=Math.cos(rot), sr=Math.sin(rot);
            let nr=(re*cr-im*sr)*gain, ni=(re*sr+im*cr)*gain;
            if(omask && !omask[k]){ nr=0; ni=0; }   // null/guard tone → dead CSI (AX211-realistic)
            let a=Math.hypot(nr,ni);
            if(st.acqReal && cal) a*=cal[k];      // per-subcarrier fixed amplitude calibration offset
            amp[k]=a;
            if(ai===st.antView){ expRe[k]=nr; expIm[k]=ni; if(k===viewK){ sampleRe=nr; sampleIm=ni; } }
          }
          // AWGN at effective SNR (EMI lowers it) — added to complex CSI so exported I/Q carries it too
          if(snrEff<44){ const sp2=amp.reduce((a,v)=>a+v*v,0)/N_SUB, np=sp2/Math.pow(10,snrEff/10), sd=Math.sqrt(np);
            for(let k=0;k<N_SUB;k++){ const noiseOn=!omask||omask[k];
              amp[k]=Math.abs(amp[k]+(noiseOn?(rng()*2-1)*sd*1.1:0));
              if(ai===st.antView && noiseOn){ expRe[k]+=(rng()*2-1)*sd*0.78; expIm[k]+=(rng()*2-1)*sd*0.78; } } }
          perAntAmp.push(amp);
        }
        const viewAmp=perAntAmp[Math.min(st.antView,perAntAmp.length-1)];

        if(st.task==="walk"||st.task==="posture"||st.night) setPerson({px,py});
        setHist(h=>[...h.slice(1),Array.from(viewAmp)]);

        // packet loss / non-uniform sampling: a dropped packet leaves a GAP in the CSI buffer
        const lossProb=(st.acqReal?ACQ.loss:0)+lossBoost;
        const dropped=lossProb>0 && rng()<lossProb;
        lossRef.current.pkt++; if(dropped) lossRef.current.drop++;
        // real capture timestamp: nominal packet time + timestamp jitter (non-uniform sampling)
        const ts=t+(st.acqReal?(rng()*2-1)*ACQ.tsJit/FS:0);
        if(!dropped){
          const meanAmp=viewAmp.reduce((a,v)=>a+v,0)/N_SUB;
          bufRef.current=[...bufRef.current.slice(-DFT_WIN),{mean:meanAmp,sub:Array.from(viewAmp)}];
          setSeries(s2=>[...s2.slice(-120),{t:+t.toFixed(1),v:+viewAmp[viewK].toFixed(4)}]);
          setIq(q=>[...q.slice(-60),{re:+sampleRe.toFixed(4),im:+sampleIm.toFixed(4)}]);
          // buffer complex CSI (view antenna) in CSIKit (n_time × n_sub) layout for export:
          // exported I/Q carries every impairment applied above → same pipeline runs on sim & real
          csiExpRef.current.push({ts:+ts.toFixed(4), re:Array.from(expRe,v=>+v.toFixed(5)), im:Array.from(expIm,v=>+v.toFixed(5))});
          if(csiExpRef.current.length>FS*12) csiExpRef.current.shift();
        }
        // SNR estimate + path count metric
        if(fN.current%20===0){
          const paths=1+ (useFurnCount(s.furn,st.useFurn)) + 8 + (present?1:0);
          setMetrics({snr:rl.snr,paths});
        }
        if(fN.current%10===0 && bufRef.current.length>30){
          const dres=runDetection(bufRef.current,t,breathSeen,snrEff);
          setDet(dres);
          // ── validation: compare estimate vs ground truth (accumulate, throttled push) ──
          const V=validRef.current;
          if(truthLabel==="breathe"){ if(dres.bpm!=null){ V.sum+=Math.abs(dres.bpm-effBpm); V.n++; }
            V.tot++; if(dres.label==="呼吸偵測") V.ok++; }
          else if(truthLabel==="empty"){ V.tot++; if(dres.label==="空間淨空") V.ok++; }
          else if(truthLabel==="walk"){ V.tot++; if(dres.label.includes("移動")) V.ok++; }
          else if(truthLabel==="apnea"){ V.tot++; if(dres.label.includes("中止")||dres.label==="呼吸偵測") V.ok++; }
          if(fN.current%30===0){ const lp=lossRef.current;
            setValid({ mae:V.n?+(V.sum/V.n).toFixed(2):null, n:V.n,
              acc:V.tot?Math.round(100*V.ok/V.tot):null, tot:V.tot,
              loss:lp.pkt?+(100*lp.drop/lp.pkt).toFixed(1):0 }); }
          // night state exposure (throttled)
          if(st.night && nightCur){ const nd=nightCur.nd;
            setNightState({stage:nightCur.stg, clockMin:nightCur.clockMin, ahi:nd.ahiTruth,
              events:nd.events.length, lossPct: lossRef.current.pkt?+(100*lossRef.current.drop/lossRef.current.pkt).toFixed(1):0}); }
          // dual estimate: generic (fixed evenly-spaced subs) vs calibrated (learned subs)
          if((st.task==="breathe"||st.task==="posture") && st.interf==="none" && !st.night){
            const nS=st.N_SUB;
            // generic = naive single fixed subcarrier (no site knowledge)
            const genericSubs=[Math.floor(nS*0.5)];
            const gBPM=bpmFromSubs(bufRef.current.slice(-DFT_WIN),genericSubs);
            // calibrated = learned best-K subcarriers for this room, fused
            const cBPM= calibProfileRef.current ? bpmFromSubs(bufRef.current.slice(-DFT_WIN),calibProfileRef.current) : gBPM;
            setCalibComp({genericBPM:gBPM,calibBPM:cBPM,truth:st.brSet});
          } else setCalibComp(null);
        }
      }
      animRef.current=requestAnimationFrame(loop);
    };
    animRef.current=requestAnimationFrame(loop);
    return ()=>cancelAnimationFrame(animRef.current);
  },[]);
  function useFurnCount(furn,on){ return on?furn.length:0; }

  useEffect(()=>{ drawHeat(cvRef.current,hist,N_SUB); },[hist,N_SUB]);

  function runDetection(buf,t,bref,snrEff){
    const recent=buf.slice(-Math.min(buf.length,FS*6)), means=recent.map(f=>f.mean);
    const mu=means.reduce((a,v)=>a+v,0)/means.length;
    const variance=means.reduce((a,v)=>a+(v-mu)**2,0)/means.length;
    let act=0; for(let i=1;i<means.length;i++)act+=Math.abs(means[i]-means[i-1]); act/=means.length;
    const nS=recent[0].sub.length;
    // ── noise-robust subcarrier selection: smooth each subcarrier (moving average)
    //    to suppress high-freq noise, THEN pick the max-variance one (breathing is slow) ──
    const SM=5;
    let bK=0,bV=-1; const varArr=new Array(nS);
    for(let k=0;k<nS;k++){
      const col=recent.map(f=>f.sub[k]);
      const sm=[]; for(let i=0;i<col.length;i++){let s=0,c=0;
        for(let j=Math.max(0,i-SM);j<=Math.min(col.length-1,i+SM);j++){s+=col[j];c++;} sm.push(s/c);}
      const m=sm.reduce((a,v)=>a+v,0)/sm.length;
      const v=sm.reduce((a,x)=>a+(x-m)**2,0)/sm.length;
      varArr[k]=v; if(v>bV){bV=v;bK=k;}
    }
    const sig=buf.slice(-DFT_WIN).map(f=>f.sub[bK]);
    const {peakHz,peakMag,total,spec}=dftBand(sig,FS,0.15,0.6);
    const periodicity=total>0?peakMag/total*spec.length:0;
    const wide=dftBand(sig,FS,0.15,1.25);
    // noise floor from high band (>0.75 Hz) + breathing-band absolute SNR
    const hi=spec.filter(s=>s.freq>0.75).map(s=>s.mag);
    const noiseEst = hi.length ? hi.reduce((a,v)=>a+v,0)/hi.length : 1e-9;
    const brSNR = peakMag/(noiseEst+1e-9);
    const wideSNR = wide.peakMag/(noiseEst+1e-9);
    // secondary peak in breathing band, EXCLUDING harmonics/subharmonics/leakage
    const band=spec.filter(s=>s.freq>=0.15&&s.freq<=0.6).sort((a,b)=>b.mag-a.mag);
    const f1=band[0]?band[0].freq:null, m1=band[0]?band[0].mag:0;
    let sec=null;
    if(f1) for(const b of band.slice(1)){
      const harm = Math.abs(b.freq-f1)<0.055
        || [2,3].some(h=>Math.abs(b.freq-h*f1)<0.05)
        || [2,3].some(h=>Math.abs(b.freq-f1/h)<0.035);
      if(!harm){ sec=b; break; }
    }
    const secRatio = sec && m1>0 ? sec.mag/m1 : 0;
    // The buffer must be substantially full before any "second fundamental" verdict:
    // a partial buffer's coarse DFT smears one breather's peak (the warm-up artifact).
    const bufFull = sig.length >= DFT_WIN*0.7;
    // ── two-person detection by MULTI-SUBCARRIER FREQUENCY AGREEMENT ──
    // A single breather modulates every sensitive subcarrier at the SAME rate, so their
    // dominant breathing-band frequencies cluster tightly. Two breathers sit at different
    // positions and dominate DIFFERENT subcarriers, so the per-subcarrier rates split into
    // two well-separated clusters. This is far more robust than a single subcarrier's
    // secondary peak (which is tripped by leakage/variability → the old false alarm).
    let bimodal=false;
    {
      const topK=Array.from(varArr.keys()).sort((a,b)=>varArr[b]-varArr[a]).slice(0,10);
      const fs2=topK.map(k=>dftBand(buf.slice(-DFT_WIN).map(f=>f.sub[k]),FS,0.15,0.6).peakHz)
        .filter(v=>v!=null).sort((a,b)=>a-b);
      if(fs2.length>=5){
        let gap=0,gi=1; for(let i=1;i<fs2.length;i++){ if(fs2[i]-fs2[i-1]>gap){gap=fs2[i]-fs2[i-1];gi=i;} }
        bimodal = gap>0.05 && gi>=2 && fs2.length-gi>=2;   // two clusters, each ≥2 subcarriers
      }
    }

    const ACT_HI=0.011, EMPTY_V=3e-5, PERIOD_HI=3.0, FAIL="#8B2020";

    // ─── FAILURE MODES (checked first) ───
    // EMI / low SNR: heavy broadband corruption, breathing peak not above noise
    if(snrEff!==undefined && snrEff<=8 && brSNR<3.0){
      return{fail:true,label:"⚠ 訊號被干擾",sub:"信雜比過低，無法擷取生理訊號",conf:0.2,bpm:null,spec,color:FAIL};}
    // Movement masking: high frame-to-frame activity dominates
    if(act>=ACT_HI){
      if(t-bref.current<15) return{fail:true,label:"⚠ 被移動干擾",sub:"大幅移動淹沒微弱呼吸訊號",conf:0.3,bpm:null,spec,color:FAIL};
      return{label:"移動 / 走路",sub:"大範圍非週期擾動",conf:Math.min(0.95,act/0.022),bpm:null,spec,color:AMBER};}
    // Non-human periodic (fan): dominant peak ABOVE breathing band, clearly beats the
    // breathing-band peak and sits well above noise (noise alone won't satisfy all three)
    if(wide.peakHz>0.48 && wide.peakHz*60>28 && wide.peakMag>1.4*peakMag && wideSNR>4){
      return{fail:true,label:"⚠ 疑似非人體週期源",sub:`偵測到 ${Math.round(wide.peakHz*60)}/min 週期，超出休息呼吸範圍（風扇？）`,conf:0.35,bpm:null,spec,color:FAIL};}
    // Two-person / mixing: sensitive subcarriers split into two distinct rate clusters
    // (a genuine second breather), on a full buffer, with strong periodicity and no gross
    // motion. One strong single breather's spectral leakage no longer trips this.
    if(bufFull && bimodal && peakHz && brSNR>4.5 && act<ACT_HI){
      return{fail:true,label:"⚠ 訊號混疊",sub:"多組週期訊號，疑似多人同床",conf:0.3,bpm:null,spec,color:FAIL};}
    // Empty room: no motion and no periodic signal at all
    if(variance<EMPTY_V && (!peakHz || periodicity<2.0))
      return{label:"空間淨空",sub:"無顯著擾動",conf:0.9,bpm:null,spec,color:GRAY};
    // Weak signal: a periodic component EXISTS but is buried near the noise floor (person too far)
    if(peakHz && periodicity>2.2 && brSNR<2.4 && variance<1.1e-4 && act<ACT_HI){
      return{fail:true,label:"⚠ 訊號過弱",sub:"呼吸訊號接近雜訊底，人可能偏離感測區（偽陰性風險）",conf:0.3,bpm:null,spec,color:FAIL};}

    // ─── NORMAL DETECTIONS ───
    if(peakHz && periodicity>PERIOD_HI && brSNR>3.0 && act<ACT_HI){ bref.current=t;
      return{label:"呼吸偵測",sub:"週期性生理訊號",conf:Math.min(0.99,periodicity/6),bpm:Math.round(peakHz*60),spec,color:SLATE}; }
    if(t-bref.current<20 && variance<1.2e-4 && periodicity<1.5)
      return{label:"⚠ 呼吸中止",sub:"週期訊號突然消失",conf:0.85,bpm:null,spec,color:RED};
    if(variance<EMPTY_V) return{label:"空間淨空",sub:"無顯著擾動",conf:0.9,bpm:null,spec,color:GRAY};
    return{label:"靜止（有人）",sub:"存在但無週期訊號",conf:0.6,bpm:null,spec,color:GREEN};
  }

  // ── site calibration action: learn this room's best subcarriers from live data ──
  function doCalibrate(){
    if(!running || calibrating) return;
    setCalibrating(true);
    // collect ~3 s of fresh data, then learn the profile
    const startLen=bufRef.current.length;
    const iv=setInterval(()=>{
      if(bufRef.current.length-startLen>=FS*3 || bufRef.current.length>=DFT_WIN){
        clearInterval(iv);
        const K = N_ANT>1?8:6;
        calibProfileRef.current=learnProfile(bufRef.current.slice(-DFT_WIN),N_SUB,K);
        setCalibrated(true); setCalibrating(false);
      }
    },200);
  }
  // ── trigger a browser download of a text payload (falls back to clipboard) ──
  function downloadFile(name,text,mime){
    try{
      const blob=new Blob([text],{type:mime||"text/plain"});
      const url=URL.createObjectURL(blob), a=document.createElement("a");
      a.href=url; a.download=name; document.body.appendChild(a); a.click();
      document.body.removeChild(a); setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(e){ try{ navigator.clipboard&&navigator.clipboard.writeText(text); }catch(_){} }
  }
  // ── the full configuration snapshot: everything needed to (a) regenerate this exact
  //    synthetic capture and (b) set up a matched real AX211 capture for comparison ──
  function scenarioManifest(){
    const V=validRef.current, lp=lossRef.current, ants=rxAntennas(rx,tx,N_ANT);
    const m={
      schema:"csi-digital-twin/manifest@1", seed,
      radio:{ f_center_Hz:F0, bandwidth_Hz:BW, n_subcarriers:N_SUB, n_antennas:N_ANT,
              sample_rate_Hz:FS, hardware:HW[hw].label, hardware_key:hw,
              ofdm_structure:ofdmStruct, ofdm_usable_subcarriers:ofdmStruct?ofdmMask(N_SUB).reduce((a,v)=>a+v,0):N_SUB },
      geometry:{ space:space, space_label:SPACES[space].label, width_m:sp.w, depth_m:sp.h,
                 tx_m:[+tx[0].toFixed(3),+tx[1].toFixed(3)], rx_m:[+rx[0].toFixed(3),+rx[1].toFixed(3)],
                 rx_antennas_m:ants.map(a=>[+a[0].toFixed(3),+a[1].toFixed(3)]),
                 person_m:[+person.px.toFixed(3),+person.py.toFixed(3)],
                 furniture:useFurn?sp.furn:[], wall_material:wallMat, wall_reflectivity:WALL_MAT[wallMat].refl,
                 ground_reflection:useGround },
      scenario:{ task, task_label:TASKS[task].label, night, apnea_type:task==="apnea"?apneaType:null,
                 interference:interf, interference_label:INTERF[interf].label,
                 heart:heart, blanket:blanket },
      impairments:{ realism, snr_dB:REALISM[realism].snr, cfo_Hz:REALISM[realism].cfo,
                    sfo_ppm:REALISM[realism].sfo, phys_realism:physReal, acq_defects:acqReal,
                    thermal_drift:thermal, packet_loss_nominal:acqReal?ACQ.loss:0,
                    ts_jitter_frac:acqReal?ACQ.tsJit:0, cal_amp_spread:acqReal?ACQ.calAmp:0, sto_rad:acqReal?ACQ.sto:0 },
      ground_truth:{ breathing_bpm:(task==="breathe"||task==="posture"||task==="apnea")?brSet:null,
                     heart_bpm:heart?72:null },
      measured:{ bpm_MAE:V.n?+(V.sum/V.n).toFixed(3):null, bpm_samples:V.n,
                 state_accuracy_pct:V.tot?+(100*V.ok/V.tot).toFixed(1):null,
                 packet_loss_pct:lp.pkt?+(100*lp.drop/lp.pkt).toFixed(1):0 },
    };
    if(night&&nightRef.current.data){ const nd=nightRef.current.data;
      m.overnight={ hypnogram:HYPNO, night_minutes:NIGHT_MIN, ahi_truth:nd.ahiTruth, ahi_motion_est:nd.ahiMotion,
        events_total:nd.events.length, by_type:nd.by,
        events:nd.events.map(e=>({at_min:+e.atMin.toFixed(2),dur_min:+e.dur.toFixed(3),type:e.type,stage:e.stage})) }; }
    return m;
  }
  function exportManifest(){
    const name=`twin_${space}_${task}${night?"_night":""}_seed${seed}.json`;
    downloadFile(name, JSON.stringify(scenarioManifest(),null,2), "application/json");
    setCopied("manifest"); setTimeout(()=>setCopied(false),1600);
  }
  // ── export the buffered complex CSI window in CSIKit (n_time × n_subcarrier) layout:
  //    columns = t_s + I0..I{N-1} + Q0..Q{N-1}. Feed into the same estimate_rate/前處理
  //    pipeline used for real AX211 → directly quantifies the sim-to-real gap (Table I–IV). ──
  function exportCSIWindow(){
    const win=csiExpRef.current; if(!win||!win.length){ setCopied("empty"); setTimeout(()=>setCopied(false),1600); return; }
    const nS=win[0].re.length;
    const head=["t_s",...Array.from({length:nS},(_,k)=>`I${k}`),...Array.from({length:nS},(_,k)=>`Q${k}`)];
    const lines=[head.join(",")];
    for(const fr of win) lines.push([fr.ts,...fr.re,...fr.im].join(","));
    const name=`csi_${space}_${task}_seed${seed}_${win.length}f.csv`;
    downloadFile(name, lines.join("\n"), "text/csv");
    setCopied("csi"); setTimeout(()=>setCopied(false),1600);
  }
  // ── export validation metrics as CSV to clipboard (for alignment with real AX211 capture) ──
  function exportValidation(){
    const V=validRef.current, lp=lossRef.current;
    const rows=[["metric","value"],["seed",seed],
      ["scenario", night?"overnight":TASKS[task].label],
      ["hardware", HW[hw].label],["space", SPACES[space].label],
      ["ofdm_structure", ofdmStruct],["blanket_cover", blanket],
      ["wall_material", WALL_MAT[wallMat].label],["ground_reflect", useGround],
      ["thermal_drift", thermal],["realism", REALISM[realism].label],
      ["phys_real", physReal],["acq_defects", acqReal],["interference", INTERF[interf].label],
      ["bpm_MAE", V.n?(V.sum/V.n).toFixed(3):"NA"],["bpm_samples", V.n],
      ["state_accuracy_pct", V.tot?(100*V.ok/V.tot).toFixed(1):"NA"],
      ["packet_loss_pct", lp.pkt?(100*lp.drop/lp.pkt).toFixed(1):"0"]];
    if(night&&nightRef.current.data){ const nd=nightRef.current.data;
      rows.push(["AHI_truth",nd.ahiTruth],["AHI_motion_est",nd.ahiMotion],
        ["events_total",nd.events.length],["events_osa",nd.by.osa],["events_csa",nd.by.csa],["events_hypo",nd.by.hypo]); }
    const csv=rows.map(r=>r.join(",")).join("\n");
    try{ navigator.clipboard&&navigator.clipboard.writeText(csv); }catch(e){}
    setCopied("csv"); setTimeout(()=>setCopied(false),1600);
  }
  // geometry
  const SVG_W=520, SVG_H=Math.round(SVG_W*sp.h/sp.w), M2PX=SVG_W/sp.w;
  const toPx=m=>[m[0]*M2PX,m[1]*M2PX];
  const propPaths=useMemo(()=>computePropPaths(tx,rx,sp.w,sp.h),[tx,rx,sp.w,sp.h]);
  propPathsRef.current=propPaths;
  const txPx=toPx(tx), pPx=toPx([person.px,person.py]);
  const antPos=rxAntennas(rx,tx,N_ANT).map(toPx);
  const svgXY=e=>{ const el=svgRef.current; if(!el)return null;
    const r=el.getBoundingClientRect(), s=e.touches?e.touches[0]:e;
    const x=(s.clientX-r.left)*(SVG_W/r.width), y=(s.clientY-r.top)*(SVG_H/r.height);
    return [Math.max(0.2,Math.min(sp.w-0.2,x/M2PX)),Math.max(0.2,Math.min(sp.h-0.2,y/M2PX))]; };
  const onMove=useCallback(e=>{ if(!drag)return; e.preventDefault(); const m=svgXY(e); if(!m)return;
    if(drag==="tx")setTx(m); else if(drag==="rx")setRx(m);
    else if(drag==="p"&&(task==="breathe"||task==="empty"))setPerson({px:m[0],py:m[1]}); },[drag,task,sp]);

  const detConf=Math.round((det.conf||0)*100), gt=TASKS[task].label;
  // expected outcome. With interference ON, the correct behaviour is a failure/low-confidence flag.
  const expectMap={twoppl:"訊號混疊",walker:"被移動干擾",emi:"訊號被干擾",faraway:"訊號過弱",fan:"非人體週期"};
  const ok=running&&(
    interf!=="none"
      // two people on ONE link is unresolvable by amplitude: honestly locking onto the
      // dominant breather (呼吸偵測) is acceptable, as is flagging mixing — both are correct.
      ? (interf==="twoppl" ? (det.fail===true||det.label==="呼吸偵測") : det.fail===true)
      : ((task==="empty"&&det.label==="空間淨空")||(task==="breathe"&&det.label==="呼吸偵測")||
         (task==="posture"&&det.label==="呼吸偵測")||(task==="walk"&&det.label.includes("移動"))||
         (task==="apnea"&&(det.label.includes("中止")||det.label==="呼吸偵測"))));
  const gtLabel = interf!=="none" ? `${gt} + ${INTERF[interf].label}` : gt;

  const btn=(a,c)=>({padding:"6px 11px",fontSize:12,cursor:"pointer",fontFamily:"inherit",borderRadius:3,
    background:a?(c||SLATE):"white",color:a?"white":GRAY,border:`1px solid ${a?(c||SLATE):HAIR}`,fontWeight:a?600:400});
  const card={background:PANEL,border:`1px solid ${HAIR}`,padding:"11px 13px",borderRadius:4};
  const lbl={fontSize:11,color:GRAY,fontStyle:"italic",margin:"0 0 7px"};

  return(
    <div style={{fontFamily:"Georgia,'Noto Serif TC',serif",background:BG,minHeight:"100vh",padding:"16px 14px 30px",color:INK}}>
      <div style={{borderBottom:`1px solid ${HAIR}`,paddingBottom:12,marginBottom:14,display:"flex",justifyContent:"space-between",alignItems:"flex-end",flexWrap:"wrap",gap:8}}>
        <div>
          <p style={{margin:"0 0 2px",fontSize:11,color:SLATE,fontStyle:"italic"}}>WiFi CSI Digital Twin · PRO · DofLab</p>
          <h1 style={{margin:0,fontSize:21,fontWeight:700}}>CSI 數位孿生控制系統</h1>
          <p style={{margin:"3px 0 0",fontSize:12,color:GRAY}}>MIMO · 材質多路徑 · 地面反射 · 採集缺陷 · OFDM結構 · 整夜情境 · 種子可重現 · 複數CSI匯出</p>
        </div>
        <button onClick={()=>{ if(!running){tRef.current=0;bufRef.current=[];breathSeen.current=-999;agcRef.current=0;csiExpRef.current=[];rngRef.current=mulberry32(seed>>>0);} setRunning(r=>!r); }}
          style={{padding:"11px 26px",fontSize:15,fontWeight:700,cursor:"pointer",fontFamily:"inherit",borderRadius:4,
                  background:running?RED:GREEN,color:"white",border:"none"}}>
          {running?"■ 停止環境":"▶ 啟動 CSI 環境"}
        </button>
      </div>

      <div style={{display:"flex",gap:14,flexWrap:"wrap",alignItems:"flex-start"}}>
        {/* LEFT config */}
        <div style={{flex:"1 1 240px",minWidth:225,display:"flex",flexDirection:"column",gap:11}}>
          <div style={card}>
            <p style={lbl}>① 硬體平台</p>
            <div style={{display:"flex",flexDirection:"column",gap:6}}>
              {Object.entries(HW).map(([k,v])=>(
                <button key={k} onClick={()=>setHw(k)} style={{...btn(hw===k),textAlign:"left"}}>
                  {v.label}　<span style={{fontSize:10,opacity:0.7}}>{v.sub}子載波 · {v.note}</span>
                </button>))}
            </div>
          </div>
          <div style={card}>
            <p style={lbl}>② 空間設定</p>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:6}}>
              {Object.entries(SPACES).map(([k,v])=>(<button key={k} onClick={()=>setSpace(k)} style={btn(space===k)}>{v.label}</button>))}
            </div>
            <label style={{display:"flex",alignItems:"center",gap:6,margin:"9px 0 0",fontSize:12,color:GRAY,cursor:"pointer"}}>
              <input type="checkbox" checked={useFurn} onChange={e=>setUseFurn(e.target.checked)}/> 含家具多路徑
            </label>
          </div>
          <div style={card}>
            <p style={lbl}>③ 任務 / 動作</p>
            <div style={{display:"flex",flexDirection:"column",gap:5}}>
              {Object.entries(TASKS).map(([k,v])=>(<button key={k} onClick={()=>setTask(k)} style={{...btn(task===k),textAlign:"left"}}>
                {v.label}　<span style={{fontSize:10,opacity:0.7}}>{v.desc}</span></button>))}
            </div>
            {(task==="breathe"||task==="posture"||task==="apnea")&&(
              <>
                <div style={{display:"flex",gap:5,flexWrap:"wrap",marginTop:9}}>
                  {[12,15,18,20].map(r=>(<button key={r} onClick={()=>setBrSet(r)} style={btn(brSet===r)}>{r}</button>))}
                  <span style={{fontSize:11,color:GRAY,alignSelf:"center"}}>BPM</span>
                </div>
                {(task==="breathe"||task==="posture")&&(
                  <label style={{display:"flex",alignItems:"center",gap:6,margin:"8px 0 0",fontSize:12,color:GRAY,cursor:"pointer"}}>
                    <input type="checkbox" checked={heart} onChange={e=>setHeart(e.target.checked)}/> 疊加心跳 (72 BPM, ±1.5mm)
                  </label>)}
                {task==="apnea"&&(
                  <div style={{marginTop:9}}>
                    <p style={{margin:"0 0 5px",fontSize:11,color:GRAY}}>臨床事件類型：</p>
                    <div style={{display:"flex",flexDirection:"column",gap:4}}>
                      {Object.entries(APNEA_TYPES).map(([k,v])=>(
                        <button key={k} onClick={()=>setApneaType(k)} style={{...btn(apneaType===k,k==="osa"?RED:SLATE),textAlign:"left",fontSize:11}}>
                          {v.label}　<span style={{fontSize:9,opacity:0.7}}>{v.desc}</span></button>))}
                    </div>
                    <p style={{margin:"6px 0 0",fontSize:10,color:apneaType==="osa"?RED:GRAY,lineHeight:1.4}}>
                      {APNEA_TYPES[apneaType].note}
                    </p>
                  </div>)}
              </>)}
          </div>
          <div style={card}>
            <p style={lbl}>④ 真實度（硬體損傷）</p>
            <div style={{display:"flex",gap:6}}>
              {Object.entries(REALISM).map(([k,v])=>(<button key={k} onClick={()=>setRealism(k)} style={btn(realism===k)}>{v.label}</button>))}
            </div>
            <p style={{margin:"8px 0 0",fontSize:10,color:GRAY,lineHeight:1.5}}>
              SNR {REALISM[realism].snr}dB · CFO {REALISM[realism].cfo}Hz · SFO {REALISM[realism].sfo}ppm · AGC/抖動
            </p>
            <div style={{marginTop:9,paddingTop:9,borderTop:`1px solid ${HAIR}`}}>
              <label style={{display:"flex",alignItems:"center",gap:7,cursor:"pointer"}}>
                <input type="checkbox" checked={physReal} onChange={e=>setPhysReal(e.target.checked)}/>
                <span style={{fontSize:12,fontWeight:600,color:physReal?AMBER:INK}}>物理真實度層</span>
              </label>
              <p style={{margin:"5px 0 0",fontSize:10,color:GRAY,lineHeight:1.5}}>
                {physReal
                  ? "已啟用：延展人體(胸腹)＋呼吸變異＋擴散散射(Rician)＋背景微動。訊號更接近真實、更難偵測。"
                  : "關閉＝理想化（點散射＋正弦呼吸）。開啟後模擬真實物理，偵測難度上升約數倍。"}
              </p>
              <label style={{display:"flex",alignItems:"center",gap:6,margin:"8px 0 0",fontSize:12,color:GRAY,cursor:"pointer"}}>
                <input type="checkbox" checked={blanket} onChange={e=>setBlanket(e.target.checked)}/> 棉被遮蔽（人體散射 ×0.55）
              </label>
            </div>
          </div>
          <div style={card}>
            <p style={lbl}>④b 通道物理 · 邊界材質</p>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:6}}>
              {Object.entries(WALL_MAT).map(([k,v])=>(
                <button key={k} onClick={()=>setWallMat(k)} style={{...btn(wallMat===k),fontSize:11}}>{v.label}</button>))}
            </div>
            <p style={{margin:"6px 0 0",fontSize:10,color:GRAY,lineHeight:1.4}}>{WALL_MAT[wallMat].note}（反射係數 ×{WALL_MAT[wallMat].refl}）</p>
            <label style={{display:"flex",alignItems:"center",gap:6,margin:"9px 0 0",fontSize:12,color:GRAY,cursor:"pointer"}}>
              <input type="checkbox" checked={useGround} onChange={e=>setUseGround(e.target.checked)}/> 地面反射（3D 樓板彈跳）
            </label>
            <label style={{display:"flex",alignItems:"center",gap:6,margin:"6px 0 0",fontSize:12,color:GRAY,cursor:"pointer"}}>
              <input type="checkbox" checked={thermal} onChange={e=>setThermal(e.target.checked)}/> 環境熱漂移（靜態通道緩慢變化）
            </label>
          </div>
          <div style={{...card,borderColor:acqReal?AMBER:HAIR}}>
            <p style={{...lbl,color:acqReal?AMBER:GRAY}}>④c 真實 CSI 採集缺陷</p>
            <label style={{display:"flex",alignItems:"center",gap:7,cursor:"pointer"}}>
              <input type="checkbox" checked={acqReal} onChange={e=>setAcqReal(e.target.checked)}/>
              <span style={{fontSize:12,fontWeight:600,color:acqReal?AMBER:INK}}>啟用採集缺陷層</span>
            </label>
            <p style={{margin:"5px 0 0",fontSize:10,color:GRAY,lineHeight:1.5}}>
              {acqReal
                ? `已啟用：封包遺失(~${Math.round(ACQ.loss*100)}%)造成非均勻採樣缺口＋時戳抖動＋每子載波振幅校正偏移＋STO 相位斜坡。這是 sim→real 最大落差。`
                : "關閉＝理想均勻採樣。真實 Intel CSI 封包不等距、有遺失、每子載波振幅需校正。"}
            </p>
            <label style={{display:"flex",alignItems:"center",gap:7,margin:"9px 0 0",paddingTop:9,borderTop:`1px solid ${HAIR}`,cursor:"pointer"}}>
              <input type="checkbox" checked={ofdmStruct} onChange={e=>setOfdmStruct(e.target.checked)}/>
              <span style={{fontSize:12,fontWeight:600,color:ofdmStruct?AMBER:INK}}>AX211 子載波結構</span>
            </label>
            <p style={{margin:"5px 0 0",fontSize:10,color:GRAY,lineHeight:1.5}}>
              {ofdmStruct
                ? `已啟用：null DC 子載波＋兩側 guard band 為無效 CSI（熱圖呈死區、偵測自動排除）。可用子載波 ${ofdmMask(N_SUB).reduce((a,v)=>a+v,0)}/${N_SUB}。`
                : "關閉＝所有子載波皆有效。真實 802.11 OFDM 的 DC/邊帶不可用。"}
            </p>
          </div>
          {/* ── reproducibility: seed governs every stochastic term → same seed+config = identical capture ── */}
          <div style={{...card,borderColor:SLATE}}>
            <p style={{...lbl,color:SLATE}}>④d 實驗可重現性 · 隨機種子</p>
            <div style={{display:"flex",alignItems:"center",gap:8}}>
              <input type="number" value={seed} onChange={e=>setSeed(Math.max(0,Math.floor(+e.target.value||0)))}
                style={{width:96,padding:"5px 7px",fontSize:13,fontFamily:"inherit",border:`1px solid ${HAIR}`,borderRadius:3,color:INK,background:"white"}}/>
              <button onClick={()=>setSeed(s=>((s*1664525+1013904223)>>>0)%100000)} style={{...btn(false),fontSize:11}}>換一個</button>
            </div>
            <p style={{margin:"7px 0 0",fontSize:10,color:GRAY,lineHeight:1.5}}>
              種子固定＝AWGN／CFO抖動／擴散／AGC／封包遺失／STO 全部可重現。相同 seed＋設定會產生逐幀相同的合成擷取，
              才能與真實 AX211 擷取一對一對比、或做消融時只變一個因子。
            </p>
          </div>
          <div style={{...card,borderColor:night?SLATE:HAIR}}>
            <label style={{display:"flex",alignItems:"center",gap:7,cursor:"pointer"}}>
              <input type="checkbox" checked={night} onChange={e=>setNight(e.target.checked)}/>
              <span style={{fontSize:12,fontWeight:700,color:night?SLATE:INK}}>⑤ 整夜睡眠情境（時間壓縮）</span>
            </label>
            <p style={{margin:"5px 0 0",fontSize:10,color:GRAY,lineHeight:1.5}}>
              {night
                ? `約 ${NIGHT_SECS}s 播完一整夜：睡眠階段 hypnogram 驅動呼吸率與變異、姿態轉換、叢集事件（含 Cheyne-Stokes）＋即時 AHI。覆寫上方任務。`
                : "開啟後模擬整夜：睡眠分期、姿態轉換、呼吸中止事件叢集、即時 AHI 與事件時間軸。"}
            </p>
          </div>
          <div style={{...card,borderColor:interf==="none"?HAIR:RED,opacity:night?0.5:1}}>
            <p style={{...lbl,color:interf==="none"?GRAY:RED}}>⑤b 失敗場景 / 干擾{night?"（整夜模式停用）":""}</p>
            <div style={{display:"flex",flexDirection:"column",gap:5}}>
              {Object.entries(INTERF).map(([k,v])=>(
                <button key={k} onClick={()=>setInterf(k)}
                  style={{...btn(interf===k, k==="none"?SLATE:RED),textAlign:"left"}}>
                  {v.label}　<span style={{fontSize:10,opacity:0.7}}>{v.desc}</span>
                </button>))}
            </div>
          </div>
        </div>

        {/* CENTER twin */}
        <div style={{flex:"1 1 330px",minWidth:300}}>
          <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:6}}>
            <p style={{...lbl,margin:0}}>數位孿生視圖 · {sp.label}</p>
            <div style={{display:"flex",gap:6,alignItems:"center"}}>
              <button onClick={()=>setShowProp(v=>!v)} style={btn(showProp)}>{showProp?"● 傳播視圖":"傳播視圖"}</button>
              {N_ANT>1&&(<>
                <span style={{fontSize:11,color:GRAY,alignSelf:"center"}}>顯示天線</span>
                {Array.from({length:N_ANT},(_,i)=>(<button key={i} onClick={()=>setAntView(i)} style={btn(antView===i)}>Rx{i+1}</button>))}
              </>)}
            </div>
          </div>
          <svg ref={svgRef} viewBox={`0 0 ${SVG_W} ${SVG_H}`}
            style={{width:"100%",border:`1.5px solid ${SLATE}`,display:"block",background:BG,touchAction:"none",userSelect:"none",
                    cursor:drag?"grabbing":"default",opacity:running?1:0.7}}
            onMouseMove={onMove} onMouseUp={()=>setDrag(null)} onMouseLeave={()=>setDrag(null)}
            onTouchMove={onMove} onTouchEnd={()=>setDrag(null)}>
            {Array.from({length:Math.floor(sp.w)+1},(_,i)=>(<line key={`x${i}`} x1={i*M2PX} y1={0} x2={i*M2PX} y2={SVG_H} stroke={HAIR} strokeWidth={0.5}/>))}
            {Array.from({length:Math.floor(sp.h)+1},(_,i)=>(<line key={`y${i}`} x1={0} y1={i*M2PX} x2={SVG_W} y2={i*M2PX} stroke={HAIR} strokeWidth={0.5}/>))}
            <rect x={0} y={0} width={SVG_W} height={SVG_H} fill="none" stroke={INK} strokeWidth={4}/>
            {/* furniture */}
            {useFurn&&sp.furn.map((f,i)=>{const [fx,fy]=toPx([f.x,f.y]);return(
              <g key={i}>
                <rect x={fx-14} y={fy-10} width={28} height={20} rx={2} fill="none" stroke={LINEN} strokeWidth={1.5}/>
                <text x={fx} y={fy+3} textAnchor="middle" fill={LINEN} fontSize={9} fontFamily="sans-serif">{f.n}</text>
              </g>);})}
            {/* ripples */}
            {running&&[0,40,80].map((o,i)=>{const r=((rip+o)%120)*(SVG_W/200);
              return <circle key={i} cx={txPx[0]} cy={txPx[1]} r={Math.max(0,r)} fill="none" stroke={SLATE} strokeWidth={0.9} opacity={Math.max(0,0.4-r/SVG_W)}/>;})}
            {/* multipath propagation view */}
            {showProp&&propPaths.map((p,pi)=>{ const col=p.type==="direct"?SLATE:AMBER; const pts=p.pts.map(toPx);
              return <g key={`pp${pi}`}>
                <polyline points={pts.map(q=>`${q[0]},${q[1]}`).join(" ")} fill="none" stroke={col} strokeWidth={1.3} opacity={0.32}/>
                {p.pts.length>2&&<circle cx={pts[1][0]} cy={pts[1][1]} r={2.6} fill={col} opacity={0.7}/>}
                {running&&pulsesRef.current.map((pl,li)=>{ const wp=posAlong(p.pts,(fN.current-pl.f0)*PROP_SPEED); if(!wp)return null; const s=toPx(wp);
                  return <circle key={li} cx={s[0]} cy={s[1]} r={3.4} fill={col}/>; })}
              </g>; })}
            {showProp&&<g>
              <rect x={8} y={8} width={182} height={64} rx={5} fill="white" opacity={0.9} stroke={HAIR}/>
              <text x={17} y={26} fontSize={11.5} fill={INK} fontFamily="sans-serif">發射 Tx：{propStats.tx} 次</text>
              <text x={17} y={43} fontSize={11.5} fill={INK} fontFamily="sans-serif">接收 Rx：{propStats.rx} 個（多路徑副本）</text>
              <text x={17} y={62} fontSize={11.5} fill={SLATE} fontFamily="sans-serif" fontWeight="700">接收/發射 = {propStats.tx?(propStats.rx/propStats.tx).toFixed(1):"0"}× · {propPaths.length} 條路徑</text>
            </g>}
            {/* paths to viewed antenna */}
            <line x1={txPx[0]} y1={txPx[1]} x2={antPos[antView][0]} y2={antPos[antView][1]} stroke={SLATE} strokeWidth={1.6} strokeDasharray="9 5" opacity={0.5}/>
            {task!=="empty"&&<>
              <line x1={txPx[0]} y1={txPx[1]} x2={pPx[0]} y2={pPx[1]} stroke={INK} strokeWidth={1} strokeDasharray="4 4" opacity={0.2}/>
              <line x1={pPx[0]} y1={pPx[1]} x2={antPos[antView][0]} y2={antPos[antView][1]} stroke={INK} strokeWidth={1} strokeDasharray="4 4" opacity={0.2}/>
            </>}
            {running&&(task==="breathe"||task==="posture"||task==="apnea")&&(
              <circle cx={pPx[0]} cy={pPx[1]} r={20+6*Math.abs(Math.sin(rip*0.15))} fill="none" stroke={SLATE} strokeWidth={1.6} opacity={0.5}/>)}
            {task!=="empty"&&(<g onMouseDown={()=>{if(task==="breathe")setDrag("p");}} onTouchStart={()=>{if(task==="breathe")setDrag("p");}} style={{cursor:task==="breathe"?"grab":"default"}}>
              <circle cx={pPx[0]} cy={pPx[1]} r={15} fill={INK} opacity={0.9}/>
              <text x={pPx[0]} y={pPx[1]+4} textAnchor="middle" fill={BG} fontSize={10} fontFamily="sans-serif">人</text></g>)}
            <g onMouseDown={()=>setDrag("tx")} onTouchStart={()=>setDrag("tx")} style={{cursor:"grab"}}>
              <rect x={txPx[0]-22} y={txPx[1]-14} width={44} height={28} rx={4} fill={SLATE}/>
              <text x={txPx[0]} y={txPx[1]+5} textAnchor="middle" fill="white" fontSize={12} fontWeight="700" fontFamily="sans-serif">Tx</text></g>
            {/* interference markers */}
            {running&&interf!=="none"&&iMark.map((m,i)=>{const [mx,my]=toPx([m.x,m.y]);return(
              <g key={`im${i}`}>
                <circle cx={mx} cy={my} r={13} fill={RED} opacity={m.label==="風扇"?0.4:0.7}/>
                <text x={mx} y={my+4} textAnchor="middle" fill="white" fontSize={9} fontFamily="sans-serif">{m.label}</text>
              </g>);})}
            {/* Rx antennas */}
            {antPos.map((a,i)=>(
              <g key={i} onMouseDown={()=>setDrag("rx")} onTouchStart={()=>setDrag("rx")} style={{cursor:"grab"}}>
                <rect x={a[0]-19} y={a[1]-12} width={38} height={24} rx={3}
                  fill={i===antView?"#273D4A":"#3A4A55"} stroke={i===antView?SLATE:HAIR} strokeWidth={i===antView?1.8:1}/>
                <text x={a[0]} y={a[1]+4} textAnchor="middle" fill="white" fontSize={10} fontWeight="700" fontFamily="sans-serif">Rx{N_ANT>1?i+1:""}</text>
              </g>))}
            {!running&&(<text x={SVG_W/2} y={SVG_H/2} textAnchor="middle" fill={GRAY} fontSize={15} fontFamily="sans-serif" opacity={0.6}>按「啟動 CSI 環境」開始</text>)}
          </svg>
          <div style={{display:"flex",gap:8,marginTop:8}}>
            <div style={{...card,flex:1,padding:"8px 11px"}}>
              <p style={{margin:0,fontSize:10,color:GRAY}}>子載波 / 天線</p>
              <p style={{margin:0,fontSize:16,fontWeight:700,color:SLATE}}>{N_SUB} × {N_ANT}</p>
            </div>
            <div style={{...card,flex:1,padding:"8px 11px"}}>
              <p style={{margin:0,fontSize:10,color:GRAY}}>多路徑數</p>
              <p style={{margin:0,fontSize:16,fontWeight:700,color:SLATE}}>{running?metrics.paths:"—"}</p>
            </div>
            <div style={{...card,flex:1,padding:"8px 11px"}}>
              <p style={{margin:0,fontSize:10,color:GRAY}}>SNR</p>
              <p style={{margin:0,fontSize:16,fontWeight:700,color:SLATE}}>{running?`${metrics.snr}dB`:"—"}</p>
            </div>
          </div>
        </div>

        {/* RIGHT detection + I/Q */}
        <div style={{flex:"1 1 260px",minWidth:245,display:"flex",flexDirection:"column",gap:11}}>
          {running&&det.fail&&(
            <div style={{background:"#F7E9E9",border:`1.5px solid ${RED}`,borderRadius:4,padding:"9px 13px"}}>
              <p style={{margin:0,fontSize:13,fontWeight:700,color:RED}}>偵測失敗 · 系統誠實回報</p>
              <p style={{margin:"3px 0 0",fontSize:11,color:INK,lineHeight:1.4}}>此為系統能力邊界之一：不硬給假答案，而是標示無法可靠辨識。</p>
            </div>)}
          <div style={{...card,borderColor:det.color||HAIR,borderWidth:1.5}}>
            <p style={lbl}>⑥ 偵測結果</p>
            <p style={{margin:"0 0 2px",fontSize:25,fontWeight:700,color:det.color||INK}}>{running?det.label:"未啟動"}</p>
            <p style={{margin:"0 0 8px",fontSize:12,color:GRAY}}>{running?det.sub:"請啟動環境"}</p>
            {det.bpm&&running&&(<p style={{margin:"0 0 6px",fontSize:15}}>估算呼吸率 <b style={{fontSize:20,color:SLATE}}>{det.bpm}</b> BPM</p>)}
            {running&&(<><div style={{height:6,background:HAIR,borderRadius:3,overflow:"hidden"}}>
              <div style={{width:`${detConf}%`,height:"100%",background:det.color||SLATE,transition:"width .3s"}}/></div>
              <p style={{margin:"3px 0 0",fontSize:10,color:GRAY}}>信心 {detConf}%{det.fail?"（低信心）":""}</p></>)}
          </div>
          {running&&!night&&(<div style={{...card,padding:"9px 13px",display:"flex",alignItems:"center",justifyContent:"space-between"}}>
            <div><p style={{margin:0,fontSize:10,color:GRAY}}>設定</p><p style={{margin:0,fontSize:13,fontWeight:600}}>{gtLabel}</p></div>
            <span style={{fontSize:20}}>{ok?"✓":"…"}</span>
            <div style={{textAlign:"right"}}><p style={{margin:0,fontSize:10,color:GRAY}}>偵測</p><p style={{margin:0,fontSize:13,fontWeight:600,color:det.color||INK}}>{det.label}</p></div>
          </div>)}

          {/* ── overnight panel: hypnogram + event timeline + AHI truth vs motion-detector est ── */}
          {running&&night&&nightRef.current.data&&(()=>{
            const nd=nightRef.current.data, cm=nightState.clockMin||0;
            const tot=23*60+cm, hh=Math.floor(tot/60)%24, mm=Math.floor(tot%60);
            const clk=`${String(hh).padStart(2,"0")}:${String(mm).padStart(2,"0")}`;
            const rowY={wake:0,rem:1,n1:2,n2:3,n3:4};
            const evCol=e=>e.type==="osa"?RED:e.type==="csa"?SLATE:AMBER;
            let acc=0;
            return(
              <div style={{...card,borderColor:SLATE,borderWidth:1.5}}>
                <div style={{display:"flex",justifyContent:"space-between",alignItems:"baseline"}}>
                  <p style={{...lbl,margin:0,color:SLATE}}>⑤ 整夜睡眠 · Hypnogram</p>
                  <p style={{margin:0,fontSize:15,fontWeight:700,color:INK}}>{clk} <span style={{fontSize:11,color:STAGES[nightState.stage||"wake"].col}}>· {STAGES[nightState.stage||"wake"].label}</span></p>
                </div>
                <svg viewBox="0 0 300 46" style={{width:"100%",marginTop:6,display:"block"}}>
                  {HYPNO.map(([stg,dur],i)=>{ const x=acc/NIGHT_MIN*300,w=dur/NIGHT_MIN*300; acc+=dur;
                    return <rect key={i} x={x} y={rowY[stg]*8} width={Math.max(0.6,w-0.3)} height={7} fill={STAGES[stg].col} opacity={0.72}/>; })}
                  {nd.events.map((e,i)=>{ const x=e.atMin/NIGHT_MIN*300;
                    return <rect key={`e${i}`} x={x} y={41} width={1.6} height={5} fill={evCol(e)}/>; })}
                  <line x1={cm/NIGHT_MIN*300} y1={0} x2={cm/NIGHT_MIN*300} y2={46} stroke={INK} strokeWidth={1.1}/>
                </svg>
                <div style={{display:"flex",gap:8,marginTop:8}}>
                  <div style={{flex:1,padding:"7px 9px",background:"#EDEAE4",borderRadius:3}}>
                    <p style={{margin:0,fontSize:10,color:GRAY}}>真實 AHI（整夜排程）</p>
                    <p style={{margin:"1px 0 0",fontSize:20,fontWeight:700,color:INK}}>{nd.ahiTruth}<span style={{fontSize:10}}> /h</span></p>
                    <p style={{margin:0,fontSize:9,color:GRAY}}>OSA {nd.by.osa}·CSA {nd.by.csa}·低通氣 {nd.by.hypo}</p>
                  </div>
                  <div style={{flex:1,padding:"7px 9px",background:"#F5EAEA",borderRadius:3,border:`1px solid ${RED}`}}>
                    <p style={{margin:0,fontSize:10,color:RED}}>動作型偵測 AHI（低估）</p>
                    <p style={{margin:"1px 0 0",fontSize:20,fontWeight:700,color:RED}}>{nd.ahiMotion}<span style={{fontSize:10}}> /h</span></p>
                    <p style={{margin:0,fontSize:9,color:RED}}>漏判 {Math.round(100*(1-nd.ahiMotion/(nd.ahiTruth||1)))}%（OSA/低通氣）</p>
                  </div>
                </div>
                <p style={{margin:"6px 0 0",fontSize:10,color:GRAY,lineHeight:1.4}}>
                  動作型偵測抓 CSA（動作停），漏 OSA（有動作無氣流）與低通氣——這正是為何需要胸腹矛盾運動特徵（C3/C4）。
                </p>
              </div>);
          })()}

          {/* ── validation panel: sim estimate vs ground truth, exportable for real-data alignment ── */}
          {running&&valid&&(
            <div style={{...card,borderColor:HAIR}}>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:6,gap:6,flexWrap:"wrap"}}>
                <p style={{...lbl,margin:0}}>⑧ 驗證比對（模擬 vs 真值）</p>
                <div style={{display:"flex",gap:5,flexWrap:"wrap"}}>
                  <button onClick={exportManifest} title="完整情境設定（可重現此模擬 / 對齊真實採集）"
                    style={{padding:"4px 9px",fontSize:10,fontWeight:600,cursor:"pointer",fontFamily:"inherit",borderRadius:3,
                    background:copied==="manifest"?GREEN:SLATE,color:"white",border:"none"}}>
                    {copied==="manifest"?"✓ 情境 JSON":"情境 JSON"}
                  </button>
                  <button onClick={exportCSIWindow} title="複數 CSI 視窗（CSIKit n_time×n_sub 格式，餵同一套估測管線）"
                    style={{padding:"4px 9px",fontSize:10,fontWeight:600,cursor:"pointer",fontFamily:"inherit",borderRadius:3,
                    background:copied==="csi"?GREEN:(copied==="empty"?RED:SLATE),color:"white",border:"none"}}>
                    {copied==="csi"?"✓ CSI CSV":copied==="empty"?"無資料":"CSI 視窗"}
                  </button>
                  <button onClick={exportValidation} title="指標摘要（複製到剪貼簿）"
                    style={{padding:"4px 9px",fontSize:10,fontWeight:600,cursor:"pointer",fontFamily:"inherit",borderRadius:3,
                    background:copied==="csv"?GREEN:SLATE,color:"white",border:"none"}}>
                    {copied==="csv"?"✓ 指標":"指標 CSV"}
                  </button>
                </div>
              </div>
              <div style={{display:"flex",gap:8}}>
                <div style={{flex:1,textAlign:"center",padding:"6px 4px",background:"#F4F0EA",borderRadius:3}}>
                  <p style={{margin:0,fontSize:9,color:GRAY}}>呼吸率 MAE</p>
                  <p style={{margin:"1px 0 0",fontSize:17,fontWeight:700,color:valid.mae!=null&&valid.mae<=1?GREEN:INK}}>{valid.mae!=null?valid.mae:"—"}<span style={{fontSize:9}}> BPM</span></p>
                  <p style={{margin:0,fontSize:8,color:GRAY}}>n={valid.n}</p>
                </div>
                <div style={{flex:1,textAlign:"center",padding:"6px 4px",background:"#F4F0EA",borderRadius:3}}>
                  <p style={{margin:0,fontSize:9,color:GRAY}}>狀態正確率</p>
                  <p style={{margin:"1px 0 0",fontSize:17,fontWeight:700,color:INK}}>{valid.acc!=null?valid.acc:"—"}<span style={{fontSize:9}}> %</span></p>
                  <p style={{margin:0,fontSize:8,color:GRAY}}>n={valid.tot}</p>
                </div>
                <div style={{flex:1,textAlign:"center",padding:"6px 4px",background:valid.loss>5?"#F5EAEA":"#F4F0EA",borderRadius:3}}>
                  <p style={{margin:0,fontSize:9,color:GRAY}}>封包遺失</p>
                  <p style={{margin:"1px 0 0",fontSize:17,fontWeight:700,color:valid.loss>5?RED:INK}}>{valid.loss}<span style={{fontSize:9}}> %</span></p>
                  <p style={{margin:0,fontSize:8,color:GRAY}}>非均勻採樣</p>
                </div>
              </div>
              <p style={{margin:"6px 0 0",fontSize:9.5,color:GRAY,lineHeight:1.4,fontStyle:"italic"}}>
                模擬量測值，非真實資料。seed={seed} 下完全可重現。「情境 JSON」記錄可重建此模擬並對齊真實採集的完整設定；
                「CSI 視窗」匯出複數 CSI（CSIKit n_time×n_sub），可餵入與真實 AX211 相同的估測管線量化 sim-to-real gap（論文 Table I–IV）。
              </p>
            </div>
          )}
          {/* ── site calibration: before/after training ── */}
          {running&&!night&&(task==="breathe"||task==="posture")&&interf==="none"&&(
            <div style={{...card,borderColor:calibrated?GREEN:HAIR,borderWidth:1.5}}>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:6}}>
                <p style={{...lbl,margin:0,color:calibrated?GREEN:SLATE}}>⑦ 空間校準（訓練前後）</p>
                <button onClick={doCalibrate} disabled={calibrating||calibrated}
                  style={{padding:"5px 12px",fontSize:11,fontWeight:600,cursor:calibrated?"default":"pointer",fontFamily:"inherit",borderRadius:3,
                          background:calibrated?GREEN:(calibrating?LINEN:SLATE),color:"white",border:"none",opacity:calibrating?0.7:1}}>
                  {calibrated?"✓ 已校準":(calibrating?"校準中…":"▶ 校準此空間")}
                </button>
              </div>
              {calibComp&&(
                <div style={{display:"flex",gap:8}}>
                  <div style={{flex:1,padding:"7px 9px",background:"#F4F0EA",borderRadius:3}}>
                    <p style={{margin:0,fontSize:10,color:GRAY}}>通用模型（未校準）</p>
                    <p style={{margin:"1px 0 0",fontSize:18,fontWeight:700,color:GRAY}}>{calibComp.genericBPM??"—"}<span style={{fontSize:11}}> BPM</span></p>
                    <p style={{margin:0,fontSize:10,color:calibComp.genericBPM!=null&&Math.abs(calibComp.genericBPM-calibComp.truth)>1?RED:GRAY}}>
                      誤差 {calibComp.genericBPM!=null?Math.abs(calibComp.genericBPM-calibComp.truth):"—"} BPM</p>
                  </div>
                  <div style={{flex:1,padding:"7px 9px",background:calibrated?"#E9F0E4":"#F4F0EA",borderRadius:3,border:calibrated?`1px solid ${GREEN}`:"none"}}>
                    <p style={{margin:0,fontSize:10,color:calibrated?GREEN:GRAY}}>校準後（空間專屬）</p>
                    <p style={{margin:"1px 0 0",fontSize:18,fontWeight:700,color:calibrated?GREEN:GRAY}}>{calibrated?(calibComp.calibBPM??"—"):"—"}<span style={{fontSize:11}}> BPM</span></p>
                    <p style={{margin:0,fontSize:10,color:GRAY}}>
                      {calibrated?`誤差 ${calibComp.calibBPM!=null?Math.abs(calibComp.calibBPM-calibComp.truth):"—"} BPM`:"尚未校準"}</p>
                  </div>
                </div>
              )}
              <p style={{margin:"6px 0 0",fontSize:10,color:GRAY,lineHeight:1.4}}>
                {calibrated
                  ? "已學習此空間最靈敏的子載波並融合。切換空間或家具會使校準失效需重新校準（脆弱性）。將真實度切到「嚴苛」可見校準明顯較準。"
                  : "通用模型用單一預設子載波；校準後學習並融合此房間最靈敏的子載波。低SNR（嚴苛）下差異最明顯。"}
              </p>
            </div>
          )}
          {/* I/Q trajectory */}
          {running&&(<div style={card}>
            <p style={lbl}>複數 CSI · I/Q 平面軌跡</p>
            <ResponsiveContainer width="100%" height={140}>
              <ScatterChart margin={{top:4,right:6,bottom:4,left:-24}}>
                <CartesianGrid strokeDasharray="3 3" stroke={HAIR}/>
                <XAxis type="number" dataKey="re" tick={{fontSize:7}} domain={["auto","auto"]} name="I"/>
                <YAxis type="number" dataKey="im" tick={{fontSize:7}} domain={["auto","auto"]} name="Q"/>
                <ZAxis range={[8,8]}/>
                <Scatter data={iq} fill={SLATE} line={{stroke:LINEN,strokeWidth:1}} isAnimationActive={false}/>
              </ScatterChart>
            </ResponsiveContainer>
            <p style={{margin:"2px 0 0",fontSize:9,color:GRAY}}>呼吸使 CSI 在 I/Q 平面畫出弧形軌跡（Zhang 2024）</p>
          </div>)}
          {running&&det.spec&&det.spec.length>0&&(<div style={card}>
            <p style={lbl}>頻譜（呼吸帶）</p>
            <ResponsiveContainer width="100%" height={95}>
              <BarChart data={det.spec.filter(d=>d.freq<=1.0)} margin={{top:2,right:4,bottom:12,left:-32}} barCategoryGap={0}>
                <CartesianGrid strokeDasharray="3 3" stroke={HAIR}/>
                <XAxis dataKey="freq" tick={{fontSize:7}} interval={3} tickFormatter={v=>Math.round(v*60)} label={{value:"BPM",position:"insideBottom",offset:-3,fontSize:8}}/>
                <YAxis tick={{fontSize:7}}/>
                <Bar dataKey="mag" fill={SLATE} opacity={0.75} isAnimationActive={false}/>
                {(task==="breathe"||task==="posture"||task==="apnea")&&<ReferenceLine x={+(brSet/60).toFixed(3)} stroke={INK} strokeDasharray="4 2"/>}
              </BarChart>
            </ResponsiveContainer>
          </div>)}
          <div style={card}>
            <p style={lbl}>CSI 時頻熱圖（Rx{N_ANT>1?antView+1:""}）</p>
            <canvas ref={cvRef} width={N_SUB} height={HIST} style={{width:"100%",imageRendering:"pixelated",display:"block"}}/>
          </div>
        </div>
      </div>

      <div style={{marginTop:16,paddingTop:10,borderTop:`1px solid ${HAIR}`,fontSize:10,color:GRAY,display:"flex",justifyContent:"space-between",flexWrap:"wrap",gap:4}}>
        <span>DofLab · 國立勤益科技大學 · 智慧自動化工程系</span>
        <span style={{fontStyle:"italic"}}>合成物理模型（MIMO·材質·地面反射·CFO/SFO/AGC/STO·封包遺失·熱漂移·OFDM null/guard·種子可重現）· 僅供管線開發，非真實量測</span>
      </div>
    </div>
  );
}
