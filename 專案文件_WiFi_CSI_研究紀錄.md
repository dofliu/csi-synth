# WiFi CSI 睡眠呼吸中止居家偵測 — 專案文件與研究紀錄

> **一句話定位**：用 Wi-Fi 6E（Intel AX211, 256 子載波）的高維 CSI，做**無接觸、免穿戴、匿名**的睡眠呼吸中止（含 OSA/CSA/低通氣）居家篩檢；核心創新是**姿態感知子載波選擇（PASS）**與**分層場域校準**，並以**物理數位孿生**在真實資料到位前驗證整條演算法管線。
>
> **本文件目的**：記錄整個研究與討論過程，讓你（或協作者、或未來的 Claude 對話）能快速接手。

> **📍 目前狀態（2026-07）**：合成端管線**全部完成**——數位孿生 v3（可重現＋複數CSI匯出）、E1 高維靈敏度、C2 PASS、C3 雙任務模型、E5 跨場域校準、統一基準測試、CI、**真實資料管線骨架**都已實作、測試、合併 GitHub `main`（PR #1–#8）。**下一步唯一的關卡：採集真實 AX211 資料**，接入既有的 `load_real_csi`/`sim_to_real` 管線即可填論文 Table I–IV。詳見 §7。

---

## 0. 先回答你的問題：之後用 Claude Code 還是 Cowork？

**建議：以 Claude Code 為主，Cowork 為輔。** 理由如下。

這個專案的重心已經從「發想」轉成一個**真實的程式庫 + 即將到來的資料管線**：

| 面向 | 適合的環境 | 原因 |
|---|---|---|
| `csi_synth` Python 套件（四層＋測試＋分析腳本） | **Claude Code** | 需要版本控制、反覆改碼、跑 pytest、迭代分析——這正是 Code 的主場 |
| 互動數位孿生 `csi-digital-twin-pro.jsx` | **Claude Code** | 前端元件的除錯與擴充（例如上次的 `ORANGE` bug，在 IDE 裡即時編譯更快抓到） |
| **下一階段：真實 AX211 資料採集與處理（E1–E5）** | **Claude Code** | 這是資料分析＋腳本管線，會產生大量檔案與 git commit，Code 最合適 |
| 論文 `.docx` 隨資料更新迭代 | 兩者皆可 | Code 也能用 docx skill 產出；若一次大改敘事則 Cowork 較舒服 |
| 簡報、計畫書、文獻綜述大改 | **Cowork** | 跨多份文件的長文寫作與研究綜合，Cowork 的多步驟工作流較順 |

**具體建議做法**：
1. 把 `csi_synth/` 解壓成一個 **git repo**（例如 `github.com/dofliu/csi-synth` 或併入既有 lab repo），之後所有模擬、分析、真實資料處理都在 **Claude Code** 裡進行。
2. 論文與簡報的**大幅改寫**（例如拿到真實資料後重寫 Results、投稿前潤稿）用 **Cowork**，因為那是跨文件的長文任務。
3. 兩者共用同一個 repo：Code 負責 code 與 data，Cowork 負責 docs 與 slides，檔案都在同一個工作區。

一句話：**「碼與資料進 Code，文與圖進 Cowork」**。你現有的 MCP（filesystem、binary-writer、local-printer）在兩邊都能用。

---

## 1. 研究核心

### 1.1 目標與臨床動機
- 睡眠呼吸中止（OSA）全球約 **9.36 億**患者、約 **80% 未診斷**；黃金標準 PSG 整夜配戴、一床難求、$5,000+。
- 目標：用家中既有 Wi-Fi 做**無接觸整夜篩檢**，偵測呼吸暫停與週期異常，達到可支援居家篩檢的臨床準確度。

### 1.2 硬體與系統限制
- **擷取**：Intel AX211（Wi-Fi 6E, 802.11ax；160MHz 最多 **256 子載波**、2 天線），Monitor 模式，用 **Ubuntu Live USB** 開機（避免影響 Windows 主系統）。
- **分析**：Windows + **RTX 4080**，CSIKit + PyTorch。
- **鐵律（學術誠信）**：**AI/模擬估計值絕不可當作真實實驗數據呈現**。所有合成結果只驗證相對趨勢，數字必須用真實 AX211 資料重新驗證。

### 1.3 理論核心（本專案的推導鏈）
1. **多路徑訊號模型**：`H(f_k) = Σ_p a_p · exp(−j2π f_k d_p / c)`，拆成靜態 `H_s`（房間指紋）＋動態 `H_d(t)`（人體呼吸散射）。
2. **相位靈敏度**：`Δφ = 4π·Δd / λ`；呼吸胸腔起伏 2–6mm → @2.4GHz 約 0.2–0.6 rad（極微弱擾動）。
3. **子載波靈敏度（理論核心）**：`S_k ≈ |H_d(f_k)| · |sin(∠H_s(f_k) − ∠H_d(f_k))|`
   - 正交時最大、共線時歸零（＝Fresnel 盲點的解析來源）。
   - `∠H_s` 隨路徑長度/幾何/擺位而變 → **敏感子載波集合是「場域相依」的**。
   - 這一條式子同時解釋了：為何要高維 CSI（C1）、為何要場域校準（C4）、為何翻身要重選（C2）。
4. **融合有效信噪比**：`SNR_eff ∝ (Σ_{k∈Ω} S_k)² / (M σ²)` → 高維與校準為何有效的量化根據。

### 1.4 五大貢獻（C1–C5）
- **C1** 首次系統評估 AX211 256 子載波 CSI 的生命徵象偵測增益。
- **C2** 姿態感知子載波選擇（PASS）：翻身偵測 → 姿態指紋分類 → 動態重選敏感子載波。
- **C3** 輕量雙任務模型（呼吸率迴歸＋呼吸中止分類，<1M 參數）：`L = α·L_reg(MAE) + β·L_cls(Focal)`。
- **C4** 分層場域校準（通用底層求穩／場域校準求準／姿態自適應求續）＋與 PSG 臨床比對。
- **C5** FeitCSI/IAX 擷取工具於 AX211 的訊號品質評比。

### 1.5 通訊 vs 感測（重要教學洞察）
手機在隔間能上網，卻不能辨識呼吸：**通訊只要「有訊號到得了」**（繞射/反射繞過隔間、夠解調、有重傳糾錯）；**感測要偵測「毫米級變化量」**（<1% 振幅擾動疊在強背景上）。繞過隔間的訊號沒掃過人體、不帶呼吸資訊；帶呼吸的路徑被擋掉了。比喻：通訊像隔牆聽見說話，感測像隔牆讀唇語。

---

## 2. `csi_synth` Python 套件（四層架構）

> 交付於 `csi_synth.zip`。四層設計哲學：**乾淨物理核心 + 可選真實化/臨床/幾何層**。6 個核心測試全過（pytest）。

### 2.1 乾淨核心 `csi_synth/`
- `geometry.py`：Room / Node / Person，影像源法多路徑。
- `generator.py`：`RadioConfig`（sample_rate 預設100）、`CSIResult`（.amplitude/.phase）、`generate_csi`、`C=299792458`。
- `noise.py`：`NoiseConfig` / `apply_noise`。
- `estimate.py`、`scenarios.py`、`tests/test_validation.py`。

### 2.2 真實化層 `realism.py`（+ `realism_analysis.py`, `plot_realism.py`）
- `RespirationModel`（生理呼吸：非正弦、I:E 比、週期/振幅變異）、`BodySegment`/`default_body`（胸/腹/雙臂延展多散射，`async_level` 模擬胸腹不同步）、`RealismConfig`、`generate_csi_realistic`。
- **可報告結果**：真實度消融 → 理想化模型比全真實**樂觀約 14×**（20dB）；主導因子＝呼吸變異＋背景微動。圖：`realism_ablation_results.png`。

### 2.3 臨床層 `clinical.py`（+ `clinical_analysis.py`, `plot_clinical.py`）
- `SleepBreathingModel`（胸腹雙通道努力波形）、`ClinicalEvent`、`NORMAL/HYPOPNEA/APNEA_OSA/APNEA_CSA`、`generate_clinical_csi`、`ahi`。
- 物理正確：正常/低通氣胸腹同步（正相關）、**OSA 胸腹矛盾運動（負相關 −0.94，有動作無氣流）**、CSA 完全停止。
- **可報告結果**：naive 動作型偵測抓到 CSA（100%），**卻漏掉 OSA 與低通氣（0%）**——臨床主要兩類事件。圖：`clinical_scenario_results.png`。

### 2.4 多邊形幾何層 `polygon.py`（+ `polygon_analysis.py`, `plot_polygon.py`, `plot_shapes.py`）
- `PolygonRoom`（任意多邊形＋獨立內牆 `interior_walls`）、驗證過的射線追蹤（鏡射反射點須落在牆段上＋兩段路徑不被遮蔽，修正影像源法在凹房間的假路徑）、UTD 邊緣繞射（凹角＋自由內牆端點，`_on_outer_wall` 過濾貼牆端點）、`generate_polygon_csi`（含人體遮蔽 fallback 走繞射）。
- 建構子：`rect_room`、`l_room`、`partition_room`（隔間＋門洞）、`slanted_room`（斜牆梯形）。
- **可報告結果**：
  - L 形覆蓋圖：矩形 97% vs L 形 89% 可用覆蓋，遮蔽區靠繞射微弱抵達（`polygon_coverage_results.png`）。
  - 三形狀比較：矩形 95% / **隔間 3%（災難性遮蔽，只有門洞可感測）** / 斜牆 95%（不遮蔽但敏感子載波偏移，3/8 改變＝指紋改變）。圖：`shape_comparison_results.png`。
  - 結論：**隔間考驗「訊號可達性」（遮蔽/繞射），斜牆考驗「該用哪些子載波」（校準）**。

### 2.5 高維分集分析 `highdim_analysis.py`（+ `plot_highdim.py`）— **實驗 E1（已形式化）**
- 用指數功率延遲剖面（PDP，~5MHz 相干頻寬）建模，蒙地卡羅比較 5300 / ESP32 / AX211。
- **誠實結論**：窄頻裝置對「找到一條敏感子載波」並非無望（best-of-K 0.96）；AX211 真正的優勢是 **~8× 獨立頻率分集**（27.6 vs 3.5 looks＝160MHz÷5MHz），餵給融合 SNR_eff 與魯棒性。圖：`highdim_results.png`。
- ⚠️ 修正了原本簡報「256 才找得到敏感路徑」的不精確說法。
- **E1 形式化（本輪）**：加 `run_experiment()` 回傳結構化摘要＋**融合 SNR_eff 增益量化**：把獨立 looks 換算成 `10·log10(M)` dB 的分集/陣列增益上限——**AX211 比窄頻裝置多 ≈ +8.9 dB 融合 SNR_eff**，這是把「高維價值＝分集」講成可填 Table 的具體數字。測試 `tests/test_highdim.py` 鎖定排序（best-of-K 相近、AX211 獨立 looks >3× 且增益 >5dB、P(blind) 皆低）。

### 2.6 場域校準 `site_calibration.py`（+ `plot_calibration.py`）— **實驗 E5（已形式化）**
- **可報告結果**：6dB SNR 下，通用子載波 MAE 2.11 → 場域專屬 0.47 BPM（接近 oracle 0.50，few-shot 恢復到 0.70）；環境改變後升到 1.68，重新校準恢復 0.47。圖：`site_calibration_results.png`。
- **E5 形式化（本輪）**：測試 `tests/test_site_calibration.py` 鎖定跨場域排序——場域專屬 < 通用（校準有效）且接近 oracle、few-shot 介於兩者、感測器移動使舊模型退化（脆弱性）、重新校準恢復。可重現、可填 Table。

### 2.7 互動數位孿生 v2 真實化強化（`csi-digital-twin-pro.jsx`）

在 v1（MIMO＋家具多路徑＋二階反射＋CFO/SFO/AGC＋I/Q 軌跡）之上，依「更真實地模擬真實環境與各種狀況，且模擬可在實驗中比對驗證」的需求，加入四大真實化方向 + 一個驗證面板。**全程守鐵律：面板標示「模擬量測值，非真實資料」。**

1. **真實 CSI 採集缺陷層（④c toggle）** — sim→real 最大落差。封包遺失（~8%）造成**非均勻採樣缺口**、時戳抖動、**每子載波固定振幅校正偏移**（`makeCalib`，Intel CSI 特性）、**STO 每封包相位斜坡**。開啟後偵測明顯變難，逼近真實髒訊號。
2. **整夜睡眠情境（⑤ toggle）** — 約 90 秒播完一整夜：`HYPNO` 睡眠分期（Wake/N1/N2/N3/REM）驅動呼吸率與變異、姿態轉換、事件叢集（REM/淺睡權重高），**CSA 以 Cheyne-Stokes 漸強漸弱包絡**。右側 hypnogram 條帶＋事件時間軸＋移動時鐘，並對比**真實 AHI vs 動作型偵測 AHI**——後者刻意低估 OSA/低通氣，直接對應 C4 臨床論點（動作型偵測漏 OSA）。
3. **通道物理深化（④b）** — 四種邊界材質（乾牆/混凝土/玻璃/木質）改變反射係數與指紋陡度（`WALL_MAT`→`wallImages`）、**3D 地面反射**樓板彈跳（`floorPathLen`）、**環境熱漂移**使靜態通道緩慢起伏。
4. **更多共存干擾（⑤b）** — 在原 5 種之上新增：寵物移動、空調 0.02Hz 週期起伏、同頻/流量突發封包遺失（與採集缺陷層連動 `lossBoost`）。
5. **驗證比對面板（⑧）** — 即時累計**呼吸率 MAE**、**狀態正確率**、**封包遺失率**，一鍵**匯出 CSV**（含硬體/空間/材質/真實度/干擾/AHI 真值與動作型估計等欄位）→ 直接與真實 AX211 擷取結果對齊，**填論文 Table I–IV 的驗證骨架**。

> 工程備忘：本 session 中「對既有檔案的即時編輯」無法同步到 Linux 測試沙箱（新建檔案可以），故 v2 以完整逐行審查驗證取代 esbuild（花括號/JSX 標籤配對、變數定義全數確認）。日後在 Claude Code 內開發時 esbuild 可正常運作。

### 2.8 互動數位孿生 v3：可重現性 + 複數 CSI 匯出（實驗對比橋接）

v3 的核心動機來自需求的第二句：**「必須是之後實驗可以對比驗證的」**。v2 已有豐富物理真實度，但有兩個致命缺口讓它「無法與真實實驗對比」：**(1) 不可重現**（所有 AWGN/CFO抖動/擴散/AGC/封包遺失/STO 都用 `Math.random()`，每次跑都不同，無法重跑同一次合成擷取去對齊真實擷取）；**(2) 只匯出小小的指標 CSV**，沒有匯出真正的複數 CSI 或設定快照，因此和 CSIKit `(n_time, n_subcarriers)` 管線（Table I–IV 要用的）之間沒有實際橋樑。v3 補上這兩點，並加了幾項真實情境：

1. **種子可重現（④d）** — 以 `mulberry32(seed)` 流式 PRNG 取代所有 `Math.random()`。**相同 seed＋設定＝逐幀完全相同的合成擷取**。這是「實驗可對比」的前提：才能(a)重跑同一次模擬去對齊真實 AX211 擷取、(b)做消融時只變一個因子而其餘雜訊完全固定。UI 有種子輸入框＋「換一個」。
2. **複數 CSI 匯出（⑧「CSI 視窗」按鈕）** — 緩衝觀測天線的複數 CSI，以 **CSIKit `(n_time × n_subcarrier)` 版面**匯出 CSV：欄位 `t_s, I0..I{N-1}, Q0..Q{N-1}`。**匯出的 I/Q 帶有上游所有損傷**（AWGN/CFO/SFO/AGC/STO/每子載波校正/封包遺失缺口/null-guard 死區），時戳為真實的抖動/遺失時戳。→ 可餵入與真實 AX211 **同一套** `estimate_rate`／前處理管線，直接量化 sim-to-real gap。
3. **情境 JSON 匯出（⑧「情境 JSON」按鈕）** — 完整設定快照（schema `csi-digital-twin/manifest@1`）：seed、radio（含 OFDM 可用子載波數）、幾何（Tx/Rx/各天線/人/家具座標）、材質/地面/熱漂移、任務/干擾/呼吸真值/整夜 hypnogram 與事件排程、即時量測指標。→ 可**重建此模擬**，也可據以**佈置一個條件相符的真實擷取**做一對一比較。
4. **AX211 子載波結構（④c）** — `ofdmMask`：null DC 子載波＋兩側 guard band 為無效 CSI（熱圖呈死區、偵測與校準自動排除、匯出為零）。256→231 可用（接近 AX211 實際可用數）。讓匯出的 CSI 與熱圖符合真實擷取結構。
5. **更真實的生理／情境** — 心跳改為獨立頻帶（~1.0–1.3Hz + HRV）的 `realHeart`（呼吸帶與心跳帶可分辨，驗證雙頻帶估測）；新增**週期性肢動 PLMD**（每~30s 抽動一次的非呼吸週期源）與**棉被遮蔽**（人體散射 ×0.55，測靈敏度下降）。

**Python 端橋接（`csi_synth/twin_import.py`）**：`load_twin_csi(csv, manifest)` 把孿生匯出的 CSV+JSON 重建成 `CSIResult`（複數 `(n_time, n_sub)`、非均勻時戳、真值標籤），`resample_uniform` 補到均勻格點；於是**同一套 `estimate_rate` 同時跑孿生輸出與（未來的）真實擷取**。round-trip 測試（`tests/test_twin_import.py`）證明：即使 8% 封包遺失＋時戳抖動，仍還原呼吸率誤差 <1 BPM。全套 8 個測試通過。

> **這一段就是「模擬 → 實驗對比驗證」的具體實作**：孿生產生帶標籤的合成 CSI（可重現、CSIKit 格式），真實 AX211 產生同格式 CSI，兩者過同一管線 → 差距即 sim-to-real gap，填論文 Table I–IV。

### 2.9 姿態感知子載波選擇 PASS（貢獻 C2）— 含誠實負面結果

在合成管線上把 C2（PASS）做成可跑的模組＋消融實驗（對應實驗 E3）。**模組** `csi_synth/pass_select.py`：子載波敏感度 `S_k` 選擇、翻身偵測（低頻平滑後的動作叢發）、姿態指紋（呼吸帶能量分布，非原始 |H|）分類、`PASSTracker` 線上迴圈（偵測→分類→重選）。**實驗** `pass_analysis.py`（圖 `pass_results.png`、測試 `tests/test_pass.py`，全套 14 測試通過）。一房間、含翻身的整夜、低 SNR。誠實報告四件事：

1. **前提成立**：敏感子載波集合是姿態相依的——非仰臥姿態與仰臥 top-K 的重疊僅 0–33%，指紋彼此可分。✓
2. **翻身偵測 100% recall**（0 false pos）。**姿態分類：單天線 33% → 雙天線（AX211 MIMO）72–82%**。這是關鍵物理洞察：**單一 Tx–Rx 鏈路無法區分對 LoS 軸鏡像對稱的姿態（左/右側臥散射路徑長幾乎相同）**，需第二根天線打破對稱——**直接佐證 AX211 雙天線的必要性**。
3. **強效益＝翻身門控**：動作淹沒呼吸時，naive 估計在翻身視窗產生大誤差（最壞 6 BPM）；PASS 偵測翻身並抑制輸出 → 呼吸率 MAE 1.12 → 0.53（×2.1），**移除會造成呼吸中止誤報的動作誤差**。這是孿生內最直接、最強的 PASS 效益。
4. **誠實負面結果**：**子載波「重選」本身在單鏈路理想模型只帶來 ~3% 的融合 SNR_eff 增益**。原因是單一散射體用同一個純量胸腔位移調變「所有」子載波，每條子載波帶的呼吸資訊相近——**這與高維分析的結論一致（AX211 的價值是頻率分集/融合，不是「找到唯一好子載波」）**。真正較大的重選增益預期出現在真實豐富多路徑（深 Fresnel 陷波）與 MIMO 上，須用真實 AX211 驗證。

> **精神**：不誇大。PASS 的三個元件（翻身偵測、姿態分類、重選迴圈）端到端驗證通過；孿生內最強效益是翻身門控與 MIMO 姿態分類；「重選」在理想單鏈路偏弱且最需要真實硬體確認——這正是要寫進論文「誠實限制」與「為何需要真實資料」的內容。

### 2.10 輕量雙任務模型 C3（實驗 E4）— 呼吸率迴歸 ＋ 呼吸事件分類

把 C3 做成可跑的合成原型：一個共享 trunk、雙頭的模型，同時 (1) 迴歸呼吸率、(2) 分類呼吸事件 {正常、低通氣、OSA、CSA}，目標 `L = α·L_reg + β·L_cls`。

**資料**（`csi_synth/dual_task.py`）：24s 視窗＝12s 正常基線 → 12s 事件，來自臨床努力模型（thorax/abdomen 雙通道），涵蓋不同呼吸率/姿態/SNR。事件以**基線相對**方式呈現（真實評分就是相對基線），才看得到低通氣的部分下降與 CSA 的完全停止。

**兩個模型**：
- `dual_task_torch.py` — 論文的 **<1M 參數 BiLSTM**（共享 BiLSTM → rate 頭 + event 頭，**focal loss**），約 **329k 參數**。這是給實驗室 RTX 4080 的參考實作；PyTorch 不設為套件硬相依（此沙箱無 torch，測試以 `importorskip` 在有 torch 環境才跑，已驗證參數<1M、前向形狀、可反傳）。
- `DualTaskMLP`（純 NumPy，手寫反傳，**梯度數值檢查通過**）— 沙箱內可實跑的基線，與 BiLSTM 共用同一套資料。

**可報告結果**（`dual_task_analysis.py`、圖 `dual_task_results.png`、測試 `tests/test_dual_task.py`）：
- **呼吸率迴歸 MAE ≈ 1.4 BPM**；**事件分類 4 類 77%、事件 vs 正常 95%**。
- **臨床關鍵對比**：雙任務模型偵測率——低通氣 70%、OSA 70%、CSA 83%；**動作型偵測**——低通氣 3%、OSA 0%、CSA 57%。**雙任務救回動作型偵測完全漏掉的低通氣與 OSA**（直接對應 C4 論點）。
- **誠實限制**：**OSA 是最難的類**（易與正常混淆），因為其胸腹矛盾特徵在**單鏈路振幅**上不明顯，需要相位/雙天線 MIMO——與 §2.9 PASS 的鏡像對稱發現一致，再次指向 AX211 雙天線的價值。

> 全套 Python 測試 **19 通過＋1 skip（torch）**。所有數字為合成資料，僅驗證方法與相對趨勢；投稿前須用真實標註的 AX211 整夜資料重新訓練與驗證。

### 2.11 統一基準測試 `benchmark.py`（＋UI 佐證 `tools/twin_ui_bench.mjs`）— 詳見 `BENCHMARK.md`

把孿生從「互動探索」延伸成「系統化跑一批測試→記錄→產生可重現結果」。混合兩部分：

**A. Python 嚴謹基準矩陣** `benchmark.py`：掃描 **硬體(ESP32/AX210/AX211) × SNR × 姿態 × 真實度(理想/物理)**，每格 N seeds，記錄 **呼吸率 MAE(僅計偵測到者)＋偵測率**。輸出 `benchmark_results.csv`(60 列)＋圖 `benchmark_results.png`＋測試 `tests/test_benchmark.py`。主要結果：
- **偵測門檻**(≥90% 偵測的最低 SNR，仰臥/理想)：**ESP32 12 dB → AX210 8 dB → AX211 4 dB** —— 寬頻(256 子載波)把呼吸偵測維持到比 ESP32 深 **8 dB** 的雜訊(更多子載波可融合)。與 E1 融合增益結論一致。
- **呼吸率精度**：高 SNR 三者收斂到 **~0.5 BPM**。
- **sim-to-real 落差**：理想層平均偵測率 ~94% → 開啟**物理真實層**掉到 ~43%，量化「理想化系統性高估」。

**B. 孿生 UI 端到端佐證** `tools/twin_ui_bench.mjs`(headless Chromium 驅動打包後的 HTML)：6 個代表情境的畫面偵測 **6/6 皆合理**(呼吸/淨空/走路/EMI失敗旗標/ESP32邊緣)。過程發現兩個真實行為並**已修正**：(1) 偵測需 **~10s 暖機**填滿 DFT 緩衝→加 buffer-full 門檻；(2) 舊版「訊號混疊」用**單一子載波次峰**判兩人，對強清晰單人呼吸會誤報→**改為多子載波頻率一致性**(單人所有子載波同頻不誤報，兩人分兩叢集才判混疊)，clean 5/5 呼吸偵測。除錯發現單鏈路振幅下較強者主導 9/10 子載波、第二人難獨立主導→**單鏈路兩人偵測本質受限，偵測器現誠實鎖定較強者，真正分離需多天線 MIMO**(與 C2/C3/E1 貫穿結論一致)。

> 全套測試 **22 passed + 1 skipped**。這一節就是「設計測試 → 記錄 → 產生結果」的具體交付，等真實 AX211 資料進來，同一套基準直接重跑填 Table I–IV。

### 2.12 真實 CSI 資料處理管線 `realdata.py` ＋ `sim_to_real.py`（sim→real 橋接）

把真實擷取的 CSI 接進**與合成資料完全相同**的估測管線。流程：`擷取檔 ──CSIKit──▶ CSIData ──realdata──▶ CSIResult ──▶ estimate_rate（同 sim）`。

- **`realdata.py`**：`load_real_csi(path)` 用 CSIKit `get_reader` 自動辨識格式並讀成 canonical 複數 `(n_time, n_sub)` ＋時戳的 `CSIResult`。CSIKit 內建 **`FeitCSIBeamformReader`——正是本專案 AX211 擷取工具（FeitCSI/IAX）的格式**；也支援 IWL5300/Nexmon/ESP32/CSV。`load_streams` 每 Rx 天線一路（AX211→2，供 MIMO/PASS）。
- **`sim_to_real.py`**：`evaluate()`／`compare()` 把 real 與 twin 匯出的 sim 過**同一管線**並列比較（呼吸率、誤差、融合 SNR_eff、偵測旗標、非均勻採樣），印出 sim-to-real gap 報表——這是把「合成預測」變成「真實量測」的具體 Table I–IV 填法。
- **CSIKit 為選用相依**（拉 pandas/scikit-learn），核心保持輕量；`realdata.py` 惰性 import。
- **誠實**：估測用**振幅**（穩健）；真實 Intel/AX **相位需 sanitize**（CFO/SFO/PDD）才能做相位法，已在 `label.phase_raw_uncalibrated` 標記。真實 CSI 非均勻採樣，`sample_rate` 由時戳推得，必要時 `resample_uniform`。
- **測試 `tests/test_realdata.py`**：手上還沒有真實 AX211 檔，故用**與每個 CSIKit reader 相同結構的 mock CSIData**（帶已知呼吸調變）跑 round-trip，證明「real→CSIResult→estimate_rate」還原呼吸率 <1 BPM；檔案格式細節由 CSIKit 負責、待真實檔到位驗證。CI 新增 `test-optional` job 安裝 torch＋csikit 實跑這些測試。全套 **25 passed + 1 skipped**。

> 這一節就是「CSIKit 解析 → 同一套管線 → 填 Table」的骨架。**唯一還缺的是真實資料本身**——採到就 `load_real_csi` 進來、`sim_to_real` 比對，紅字 Table I–IV 就能換成真實量測。

---

## 3. 交付檔案清單

> ⚠️ **本節前段（3.1 起源說明）為專案早期（`outputs/` 交付、`csi_synth.zip`）的歷史紀錄，保留供脈絡參考。
> 專案現已是 GitHub repo（`dofliu/csi-synth`），所有程式以 git 版本控管、每個功能都經 PR＋CI 驗證後合併 `main`。
> **目前實際的程式結構請見本文件開頭的「專案結構」對照，或直接看 repo 根目錄的 `README.md`。**

### 3.0 現行 repo 結構速覽（git，取代下方 3.1 的 zip 交付方式）
| 路徑 | 內容 |
|---|---|
| `csi_synth/csi_synth/` | 核心套件：四層物理（`generator`/`noise`/`realism`/`clinical`/`polygon`）＋`pass_select`(C2)＋`dual_task`(C3)＋`twin_import`/`realdata`(sim↔real 橋接) |
| `csi_synth/*_analysis.py` ＋ `plot_*.py` | E1/E5/C2/C3 各實驗腳本＋統一基準 `benchmark.py`＋對應圖 |
| `csi_synth/sim_to_real.py` | real vs sim 同管線比較，sim-to-real gap 報表 |
| `csi_synth/dual_task_torch.py` | C3 的 <1M 參數 BiLSTM（PyTorch，選用相依） |
| `csi_synth/tests/`（26 測試）＋ `csi_synth/tools/twin_ui_bench.mjs` | pytest 測試套件 ＋ headless 孿生 UI 端到端佐證 |
| `csi_synth/BENCHMARK.md` | 統一基準測試報告 |
| `.github/workflows/ci.yml` | CI（pytest 矩陣＋torch/CSIKit job） |
| `csi-digital-twin-pro.jsx` | 互動數位孿生 **v3**（詳見 §2.7、§2.8） |
| `README.md`（repo 根目錄） | 專案總覽、快速開始、目前狀態表 |

歷次 PR：#1 孿生 v3 → #2 PASS(C2) → #3 雙任務(C3) → #4 CI → #5 E1/E5 → #6 統一基準 → #7 孿生誤報修正 → #8 真實資料管線。全數已合併 `main`。

### 3.1 早期交付檔案（歷史紀錄，非現行結構）
| 檔案 | 說明 |
|---|---|
| `csi_synth.zip` | （已被 git repo 取代）完整 Python 物理合成套件（四層＋分析＋測試＋圖） |
| `csi-digital-twin-pro.jsx` | **主要**互動數位孿生（React）**v2**：硬體/空間/任務/真實度/失敗場景/校準/傳播視圖＋**通道材質·地面反射·熱漂移·真實CSI採集缺陷·整夜睡眠情境·驗證比對CSV匯出**（詳見 §2.7；現已升級至 **v3**，見 §2.8） |
| `multipath-propagation-scope.html` | 獨立多路徑傳播示波器（可調速、L 形、繞射、通道脈衝響應時間軸） |
| `csi_synth_demo.png` | 孿生四面板示意圖 |

### 3.2 論文
| 檔案 | 說明 |
|---|---|
| `WiFi_CSI_Sleep_Apnea_Paper_Draft.docx` | **英文 IEEE IoT-J 論文初稿**：7 節、22 篇真實文獻、5 條方程式、**6 張圖**（Fig.1 孿生面板待補、Fig.2 真實度消融、Fig.3 L形覆蓋、Fig.4 三形狀、Fig.5 場域校準、Fig.6 臨床事件）。Table I–IV 標紅色待真實 AX211 資料 |
| `論文第二章_文獻探討.docx`、`論文第三章_場域校準小節.docx`、`論文後續章節規劃書.docx` | 中文章節素材 |

### 3.3 簡報
| 檔案 | 說明 |
|---|---|
| `WiFi_CSI_完整研究簡報.pptx` | **最完整**：32 張，願景＋**擴充理論(6張)**＋文獻＋實證＋貢獻＋方法＋應用＋路線（dof-podium） |
| `WiFi_CSI_探索過程_教學簡報.pptx` | 11 張教學/演講版，探索過程敘事 |
| `WiFi_CSI_研究提案簡報.pptx` | 20 張原始提案（活點地圖/白眼/凝 比喻） |
| `WiFi_CSI_技術簡報.pptx` | 26 張早期技術簡報 |

### 3.4 圖表（可重複用於論文/簡報）
`realism_ablation_results.png`、`shape_comparison_results.png`、`polygon_coverage_results.png`、`site_calibration_results.png`、`clinical_scenario_results.png`、`highdim_results.png`

---

## 4. 探索過程與關鍵發現（研究敘事）

這個 session 的核心價值在於**「發現問題 → 誠實面對限制 → 動手驗證」**的完整過程：

1. **理想化模型會騙人** → 建真實化層，量化出理想化樂觀 14×。
2. **房間形狀會遮蔽** → 建多邊形射線追蹤（修正影像源法凹房間假路徑＋加繞射），量化 L 形 97→89%、隔間 95→3%、斜牆指紋偏移。
3. **跨場域要校準** → 場域校準模擬 2.11→0.47，並暴露脆弱性（需可重新校準）。
4. **臨床現實會漏判** → 建臨床雙通道模型，證明動作型偵測漏掉 OSA/低通氣。
5. **高維的真義是分集** → 用 S_k 頻譜分析，誠實修正為「~8× 獨立頻率分集」而非「找到唯一好子載波」。
6. **傳播視覺化** → 互動工具把「空間多路徑 → 延遲擴散 → 頻率選擇性 → 頻寬分集」串成可視因果鏈，並統計發射/接收多路徑副本比。

**共同精神**：模擬只驗證相對趨勢與邏輯，絕不當真實數據；失敗要誠實回報（訊號不足時說「無法辨識」而非硬猜）。

---

## 5. 環境慣例與技術細節（給接手者）

- **pptx**：用 `pptx-jliu-style` skill（dof-podium 主題：BG=EEEDE9, INK=18191C, SLATE=5A6B7A；中文 Noto Serif TC、英文 EB Garamond；內文≥18–20pt；`defineSlideMaster` 母片；預設 footer「劉瑞弘 · 智慧自動化工程系 · 國立勤益科技大學 · DofLab」）。
- **docx**：docx skill，US Letter 12240×15840，方程式用 TextRun subScript/superScript。
- **JSX 陷阱**：箭頭函式 `return <tag/>` 之間要留空格；每次改動掃 `grep "return<"` 並用 esbuild 編譯。**注意**：esbuild 只抓語法錯誤，「變數未定義」（如先前 `ORANGE` 應為 `AMBER`）要到渲染該 UI 狀態才爆——改顏色/變數後要全檔交叉比對定義。
- **調色盤（twin）**：`BG, PANEL, INK, GRAY, HAIR, SLATE, LINEN, RED, GREEN, AMBER`（沒有 ORANGE）。
- **QA**：node 產生 → pandoc/markitdown 驗證 → soffice.py 轉 PDF → pdftoppm → 檢視。
- **matplotlib 中文**：`fm.fontManager.addfont(NotoSansCJK)` + `plt.rcParams["font.family"]`。

---

## 6. 誠實的限制（務必記得）

- 所有模擬數字都是**模型相對值**，非量測；投稿前必須用真實 AX211 資料重新驗證（論文 Table I–IV 仍標紅）。
- 物理模型是**乾淨近似**，系統性**高估訊號品質**（真實 CSI 更髒）；真實化層縮小但未消除 sim-to-real gap。
- UTD 繞射是**簡化係數**，捕捉定性行為非精確幅度；多邊形層是一階射線（單反射/單繞射）。
- 互動孿生的臨床子類型偵測以**教學展示**為主；嚴謹量化在 Python 分析。

---

## 7. 下一步（建議優先序 · 2026-07 更新）

**合成端全部完成**：數位孿生 v3、E1/E5、C2 PASS、C3 雙任務、統一基準測試、CI、真實資料管線骨架 —— 全數已實作、測試、合併 `main`（PR #1–#8）。**剩下唯一的關卡是真實資料本身**：

1. ~~環境建置、PASS/雙任務模型實作~~ ✅ **已完成**（合成原型 + 骨架就緒，見 §2.9、§2.10、§2.12）。
2. **真實資料採集（現在最優先）**：Ubuntu Live USB + AX211 Monitor 模式，FeitCSI/IAX 擷取驗證 → 空基線／仰臥呼吸／四姿態／翻身／插入呼吸中止，同步真值（呼吸帶，子集對 PSG）。**管線已就緒**：採到檔案後 `from csi_synth import load_real_csi` 直接接入，或 `python sim_to_real.py capture.dat --truth-bpm N` 產出對比報表。→ **Claude Code**
3. **實驗 E1–E5 真實資料重跑**：合成側排序與量化都已就緒（E1 §2.5、E3 PASS §2.9、E4 雙任務 §2.10、E5 §2.6），真實資料到位後**同一套腳本**重跑即可填論文 Table I–IV（取代紅色佔位）。**E2 工具評比**（FeitCSI vs IAX 訊號品質）待真實擷取才能開始，目前尚無合成側骨架。
4. **模型用真實資料重新訓練**：PASS 的子載波重選增益（合成側僅 ~3%，預期真實 MIMO 更大）、雙任務 BiLSTM（`dual_task_torch.py`，329k 參數）都需要真實標註資料重新驗證/訓練，不能只用合成權重。
5. **論文完稿投稿**：真實資料結果填入 Table I–IV 後，IEEE IoT-J（主場域）／IEEE Sensors Journal／ACM IMWUT。→ 大改用 **Cowork**。

---

## 8. 如何接續這個對話

專案已是 **git repo**（`dofliu/csi-synth`，GitHub），不再用 zip 交付。新對話接手時：

> 「我在做 WiFi CSI 睡眠呼吸中止居家偵測研究（AX211, 256 子載波, PASS + 場域校準 + 數位孿生），repo 在 github.com/dofliu/csi-synth。合成端管線（孿生 v3、E1/E3/E4/E5、統一基準、CI、真實資料橋接）都已完成並在 main，見 `README.md` 與 `專案文件_WiFi_CSI_研究紀錄.md`。目前在等真實 AX211 資料；我想接著做 [真實資料處理 / 論文某節 / E2 工具評比骨架 …]。」

只要在 Claude Code 中把 repo 加入 session（或本來就在此 repo），就能直接讀 `README.md`（總覽）與本文件（完整脈絡）接手；不需要再附 zip。

---

*本文件持續由開發過程更新。核心資產：`dofliu/csi-synth`（GitHub repo，程式＋測試＋CI）、`WiFi_CSI_Sleep_Apnea_Paper_Draft.docx`（論文）、`csi-digital-twin-pro.jsx`（互動孿生 v3）、`csi_synth/BENCHMARK.md`（統一基準報告）、各實驗分析圖。最後更新：2026-07（PR #8 合併，真實資料管線就緒）。*
