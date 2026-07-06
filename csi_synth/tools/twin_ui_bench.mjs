// twin_ui_bench.mjs — headless end-to-end corroboration of the interactive twin.
//
// Drives csi-digital-twin-pro.jsx (built to a standalone HTML) across a few
// scenarios and records the on-screen detection into twin_ui_results.csv + ui_*.png.
// Reads the detection as the mode of several samples (after a ~10s buffer fill) to
// avoid transient labels. Companion to the rigorous Python benchmark (benchmark.py).
//
// Prereq — build the HTML once (needs node + esbuild + react/recharts):
//   npm i esbuild react react-dom recharts playwright
//   printf '%s' 'import React from "react";import{createRoot}from"react-dom/client";\
//     import App from "../../csi-digital-twin-pro.jsx";\
//     createRoot(document.getElementById("root")).render(<App/>);' > entry.jsx
//   npx esbuild entry.jsx --bundle --loader:.jsx=jsx --jsx=automatic --minify \
//     --format=iife --outfile=twin.bundle.js
//   # wrap twin.bundle.js in <html><body><div id="root"></div><script>…</script>
//   # as csi-digital-twin-pro.html (see BENCHMARK.md), then:
//   node twin_ui_bench.mjs
//
import { chromium } from 'playwright';
import fs from 'fs';

const HTML = 'file://' + process.cwd() + '/csi-digital-twin-pro.html';
// scenario: [label, hardware, task, realism, interference, expected-substrings]
const SCENARIOS = [
  ["breathe_clean",  "Intel AX211", "靜止呼吸", "標準", "無干擾", ["呼吸偵測"]],
  ["empty",          "Intel AX211", "空間淨空", "標準", "無干擾", ["空間淨空"]],
  ["apnea",          "Intel AX211", "呼吸中止", "標準", "無干擾", ["呼吸中止","呼吸偵測"]],
  ["walk",           "Intel AX211", "走路移動", "標準", "無干擾", ["移動","走路"]],
  ["interf_emi",     "Intel AX211", "靜止呼吸", "標準", "電磁干擾", ["訊號被干擾"]],
  ["esp32_harsh",    "ESP32-S3",    "靜止呼吸", "嚴苛", "無干擾", ["呼吸偵測","靜止（有人）","訊號過弱"]],
];
const LABELS = ["呼吸偵測","移動 / 走路","空間淨空","靜止（有人）","呼吸中止","訊號被干擾",
  "被移動干擾","疑似非人體週期源","訊號混疊","訊號過弱"];

const b = await chromium.launch({ executablePath:'/opt/pw-browsers/chromium' }).catch(()=>chromium.launch());
const rows = [["scenario","hardware","task","realism","interference","detected","expected_ok"]];
for (const [name,hw,task,real,interf,exp] of SCENARIOS) {
  const p = await b.newPage({ viewport:{width:1400,height:1050} });
  await p.goto(HTML, {waitUntil:'networkidle'});
  await p.waitForTimeout(400);
  const click = async (t)=>{ await p.locator('button',{hasText:t}).first().click({timeout:4000}).catch(()=>{}); };
  await click(hw); await click(task); await click(real);
  if (interf!=="無干擾") await click(interf);
  await click("啟動 CSI 環境");
  await p.waitForTimeout(15000);          // fill the ~10s detection buffer + margin
  const reads=[];
  for (let i=0;i<5;i++){
    const d = await p.evaluate((LABELS)=>{
      const ps=[...document.querySelectorAll('p')];
      for (const el of ps){ const t=el.textContent.trim().replace(/^⚠\s*/,'');
        if (LABELS.includes(t)) return t; }
      return '(none)';
    }, LABELS);
    reads.push(d); await p.waitForTimeout(900);
  }
  const counts={}; reads.forEach(d=>counts[d]=(counts[d]||0)+1);
  const det = Object.entries(counts).sort((a,b)=>b[1]-a[1])[0][0];
  const ok = exp.some(e=>det.includes(e));
  rows.push([name,hw,task,real,interf,det,ok?"YES":"no"]);
  await p.screenshot({ path:`ui_${name}.png`, fullPage:false });
  console.log(`${name.padEnd(16)} → ${det.padEnd(12)} expect[${exp.join('/')}] ${ok?'✓':'✗'}`);
  await p.close();
}
fs.writeFileSync('twin_ui_results.csv', rows.map(r=>r.join(',')).join('\n')+'\n');
console.log('\nwrote twin_ui_results.csv');
await b.close();
