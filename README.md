# csi-synth — WiFi CSI 睡眠呼吸中止居家偵測

[![CI](https://github.com/dofliu/csi-synth/actions/workflows/ci.yml/badge.svg)](https://github.com/dofliu/csi-synth/actions/workflows/ci.yml)

用 Wi-Fi 6E（Intel **AX211**, 160MHz、**256 子載波**、2 天線）的高維 CSI，做**無接觸、免穿戴、匿名**的睡眠呼吸中止（OSA/CSA/低通氣）居家篩檢。核心創新是**姿態感知子載波選擇（PASS）**與**分層場域校準**，並以**物理數位孿生**在真實資料到位前驗證整條演算法管線。

> **學術誠信鐵律**：所有合成/模擬結果只驗證相對趨勢與邏輯，**AI/模擬估計值絕不可當作真實實驗數據呈現**。論文 Table I–IV 的數字必須用真實 AX211 資料重新驗證。

## 目前狀態（2026-07）

**合成端管線已完整、可重現、有 CI 保護；真實端橋接已就緒，等待真實 AX211 資料。**

| 面向 | 狀態 |
|---|---|
| 物理合成核心（乾淨／真實化／臨床／多邊形幾何四層） | ✅ 完成 |
| 互動數位孿生 **v3**（種子可重現 ＋ 複數 CSI 匯出 ＋ MIMO ＋ OFDM 結構） | ✅ 完成 |
| **E1** 高維靈敏度（AX211 融合 SNR 增益 +8.9 dB） | ✅ 已形式化＋測試 |
| **C2 / E3** PASS 姿態感知子載波選擇 | ✅ 合成原型＋測試 |
| **C3 / E4** 輕量雙任務模型（<1M 參數 BiLSTM ＋ NumPy 基線） | ✅ 合成原型＋測試 |
| **E5** 跨場域校準 | ✅ 已形式化＋測試 |
| 統一基準測試（硬體 × SNR × 姿態 × 真實度） | ✅ 完成 |
| CI（pytest 矩陣 × Python 3.10–3.12 ＋ torch ＋ CSIKit） | ✅ 完成 |
| **真實 CSI 資料管線**（CSIKit → 與合成相同的估測管線） | ✅ 骨架就緒，**待真實 AX211 資料接入** |
| **實驗協定**（情境分類/檔名/manifest/錄製檢查清單，見 `csi_synth/EXPERIMENT_PROTOCOL.md`） | ✅ 完成 |
| E2 擷取工具評比、論文 Table I–IV | 🔜 待照協定採集真實資料 |

## 專案結構

| 路徑 | 說明 |
|---|---|
| `csi_synth/csi_synth/` | 物理合成 Python 套件核心：`generator`／`noise`／`realism`／`clinical`／`polygon`（四層）＋`pass_select`（C2）＋`dual_task`（C3）＋`twin_import`／`realdata`（sim↔real 橋接） |
| `csi_synth/*_analysis.py`、`plot_*.py` | 各實驗腳本（E1 `highdim_analysis.py`、E5 `site_calibration.py`、C2 `pass_analysis.py`、C3 `dual_task_analysis.py`）＋統一基準 `benchmark.py`＋對應繪圖 |
| `csi_synth/sim_to_real.py` | 把真實擷取與合成匯出過**同一套估測管線**並列比較，輸出 sim-to-real gap |
| `csi_synth/dual_task_torch.py` | 論文 C3 的 <1M 參數 BiLSTM 參考實作（PyTorch，選用相依） |
| `csi_synth/tests/` | 26 個測試，鎖定每個實驗的科學排序（見下方測試表） |
| `csi_synth/tools/twin_ui_bench.mjs` | headless 驅動孿生 UI，端到端佐證 Python 基準結果 |
| `csi-digital-twin-pro.jsx` | 互動數位孿生 **v3**（React）：MIMO · 材質多路徑 · 地面反射 · 硬體損傷 · 真實 CSI 採集缺陷 · OFDM 子載波結構 · 整夜睡眠情境 · **種子可重現** · **複數 CSI／情境 JSON 匯出** |
| `csi_synth/BENCHMARK.md` | 統一基準測試報告（偵測門檻、sim-to-real 落差、UI 佐證） |
| `csi_synth/EXPERIMENT_PROTOCOL.md` | **真實資料採集實驗協定**：情境分類、檔名/manifest 規範、錄製檢查清單、如何接進 `load_real_csi`/`sim_to_real.py` |
| `AX211_CSI_建置SOP.docx` | 硬體/軟體環境建置 SOP（Live USB＋FeitCSI，到「看到熱圖」為止；正式錄製請接續看上面的 `EXPERIMENT_PROTOCOL.md`） |
| `.github/workflows/ci.yml` | CI：pytest 矩陣（3.10–3.12）＋ 選用相依（torch／CSIKit）job |
| `WiFi_CSI_Sleep_Apnea_Paper_Draft.docx` | 英文 IEEE IoT-J 論文初稿（Table I–IV 待真實資料） |
| `WiFi_CSI_*.pptx` | 研究簡報（提案／完整／教學版） |
| `專案文件_WiFi_CSI_研究紀錄.md` | 完整研究、規劃與工作紀錄（接手入口，建議先讀） |

## 五大貢獻（C1–C5）

- **C1** 首次系統評估 AX211 256 子載波 CSI 的生命徵象偵測增益 —— 合成驗證：融合 SNR_eff 比 20MHz 裝置多 **+8.9 dB**（E1）。
- **C2** 姿態感知子載波選擇（PASS）：翻身偵測 → 姿態指紋分類 → 動態重選敏感子載波 —— 合成驗證：翻身門控降呼吸率誤差 **×2.1**，雙天線姿態分類 **33%→72%**。
- **C3** 輕量雙任務模型（呼吸率迴歸＋呼吸中止分類，<1M 參數）—— 合成驗證：呼吸率 MAE **1.4 BPM**，救回動作型偵測完全漏掉的低通氣／OSA。
- **C4** 分層場域校準（通用底層／場域校準／姿態自適應）＋與 PSG 臨床比對 —— 合成驗證：通用 2.11→場域專屬 0.47 BPM（E5）。
- **C5** FeitCSI/IAX 擷取工具於 AX211 的訊號品質評比 —— 待真實資料（E2）。

## 快速開始（Python 套件）

```bash
cd csi_synth
pip install -r requirements.txt
pytest tests/ -v            # 26 個測試（torch/CSIKit 為選用相依，未裝則自動 skip）
python benchmark.py         # 統一基準：硬體 × SNR × 姿態 × 真實度
python pass_analysis.py     # C2 PASS 消融
python dual_task_analysis.py  # C3 雙任務模型
python demo_visualize.py    # 產生示意圖
```

真實資料接入（採到 AX211 擷取後）：

```python
from csi_synth import load_real_csi, estimate_rate
res = load_real_csi("capture.dat")        # FeitCSI/AX211 自動辨識（需 pip install csikit）
print(estimate_rate(res, band=(0.1, 0.6))["bpm"])
```

或用 `python sim_to_real.py capture.dat --truth-bpm 15` 直接產出 sim-to-real 對比報表。

## 授權與資料

- 本 repo 之程式與文件為 DofLab 研究產出。
- **第三方學術論文 PDF 不隨附**（見 `.gitignore`），請自行由原出版方取得。
- 尚未包含真實 AX211 量測資料；所有模擬數字為模型相對值，非量測，投稿前須用真實資料重新驗證。

---

*DofLab · 國立勤益科技大學 · 智慧自動化工程系*
