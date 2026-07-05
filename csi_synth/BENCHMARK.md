# csi_synth 統一基準測試（Benchmark）

把數位孿生從「互動探索」延伸成「系統化跑一批測試 → 記錄 → 產生可重現結果」。
分兩部分:**A. Python 嚴謹基準矩陣**(數據)＋**B. 孿生 UI 端到端佐證**(視覺)。

> ⚠️ 全部為**合成資料**,只驗證方法與**相對排序**,非絕對準確度。所有數字須用真實
> AX211 資料重新驗證。

---

## A. Python 基準矩陣 — `benchmark.py`

掃描操作包絡:**硬體(ESP32/AX210/AX211) × SNR × 姿態(仰臥/翻身) × 真實度(理想/物理)**,
每格跑 N 個 seed × 多個呼吸率,記錄 **呼吸率 MAE(僅計偵測到的視窗)** 與 **偵測率**。

```bash
python benchmark.py            # 印報告
python benchmark.py --csv      # 另存 benchmark_results.csv
python plot_benchmark.py       # 產生 benchmark_results.png
```

### 主要結果

**偵測門檻(≥90% 偵測所需的最低 SNR,仰臥/理想)——寬頻優勢的量化:**

| 裝置 | 子載波 | 偵測門檻 |
|---|---|---|
| ESP32 | 56 | **12 dB** |
| AX210 | 114 | **8 dB** |
| AX211 | 256 | **4 dB** |

→ AX211 能把呼吸偵測維持到**比 ESP32 深 8 dB** 的雜訊環境(更多子載波可融合)。

**呼吸率精度(仰臥/理想):** 高 SNR 下三者都收斂到 **~0.5 BPM**;AX211 在最高 SNR 最低。

**sim-to-real 落差:** 理想層平均偵測率 **~94%**,開啟**物理真實層**(延展人體＋Rician 擴散＋
背景微動)後掉到 **~43%** —— 物理層明顯更難,呼應「理想化模型系統性高估訊號品質」。

圖:`benchmark_results.png`(4 面板:偵測門檻、精度 vs SNR、偵測率 vs SNR、sim-to-real 落差)。
原始資料:`benchmark_results.csv`(60 列)。測試:`tests/test_benchmark.py`(鎖定排序)。

---

## B. 孿生 UI 端到端佐證 — `tools/twin_ui_bench.mjs`

用無頭 Chromium 實際驅動孿生介面(把 `csi-digital-twin-pro.jsx` 打包成 HTML 後),自動設定
情境 → 啟動 → 等偵測緩衝填滿 → 讀畫面上的偵測標籤(取多次取樣的眾數以避開瞬態)。

```bash
# 需先把 jsx 打包成 csi-digital-twin-pro.html(見下方),並 npm i playwright
node tools/twin_ui_bench.mjs      # 產生 twin_ui_results.csv + ui_*.png 截圖
```

### 結果(`twin_ui_results.csv`)— 6/6 皆為合理偵測

| 情境 | 畫面偵測 | 判定 |
|---|---|---|
| AX211 靜止呼吸 標準 | 呼吸偵測 | ✓ |
| AX211 空間淨空 | 空間淨空 | ✓ |
| AX211 呼吸中止 | 呼吸偵測(非憋氣相位時) | ✓ |
| AX211 走路移動 | 移動 / 走路 | ✓ |
| AX211 電磁干擾 | ⚠ 訊號被干擾(誠實回報失敗) | ✓ |
| ESP32 嚴苛 | 靜止(有人)（呼吸接近雜訊底,邊緣）| ✓ |

### 過程中發現的兩個真實行為(值得記錄)
1. **暖機時間**:偵測需 ~10s 才能把 DFT 緩衝填滿;讀太早(部分緩衝)會產生假的次峰 → 偶發
   「訊號混疊」誤報。實務上前 ~10s 應標為 warming-up。
2. **邊緣誤報**:對很強的單人清晰呼吸,「兩人同床/訊號混疊」偵測會**瞬態邊緣誤報**(次峰略過
   門檻)。屬偵測門檻可調的教學展示層;嚴謹量化以 Python 為準。

---

## 誠實聲明
- 互動孿生的偵測是**教學展示層**;嚴謹量化在 Python(`benchmark.py` 及各 E 實驗)。
- 所有結果為合成物理模型的相對趨勢,**絕對值須用真實 AX211 擷取重新驗證**(填論文 Table I–IV)。
