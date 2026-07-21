# 真實資料採集實驗協定

> 銜接「硬體建置 SOP」與「合成管線」之間的缺口：怎麼錄、怎麼標、怎麼命名檔案、怎麼餵進
> `load_real_csi`/`sim_to_real.py`、以及對應論文哪一個 Table/實驗。
>
> 前置：先照 `AX211_CSI_建置SOP.docx` 把 Live USB + FeitCSI 環境跑通、看到熱圖確認鏈路打通。
> **本文件從「鏈路打通之後」開始，是正式研究資料的錄製規範。**

---

## 0. 為什麼需要這份文件

一次沒有標記的錄製，事後幾乎無法用——這是實際發生過的教訓：一份學生自行測試的截圖，因為
沒記錄硬體/頻寬（子載波數對不上任何已知設定）、沒記錄當下在做什麼動作（無法判斷畫面上的
尖峰是走路、干擾還是採集缺陷）、也沒記錄房間空間配置，最後只能靠「事後猜測」重建情境，
**完全無法拿來對比合成資料或填論文 Table**。

原則很簡單：**錄製當下 3 分鐘就能寫完/量完的 metadata，事後永遠補不回來。** 本協定就是把這
3 分鐘要記的東西定下來。

---

## 1. 情境分類表（對齊 `csi_synth.scenarios` / `clinical.py`，不要自創新名詞）

錄製時**用下面的 `scenario_key` 命名**，事後才能自動對應到合成側同一套 taxonomy、同一套
`estimate_rate`/`benchmark.py` 指標、以及論文對應的實驗編號。

| `scenario_key` | 說明 | 建議時長 | 對應合成側 | 對應論文 |
|---|---|---|---|---|
| `baseline` | 空房間，完全無人 | ≥60s | `scenarios.make_scenario("baseline")` | Table I（空間淨空基準） |
| `normal-supine` | 仰臥靜息呼吸，不說話不動 | ≥120s（愈長愈能估變異性） | `"normal-supine"` | Table I（呼吸率 MAE）、E1 |
| `posture-supine` / `posture-left-lateral` / `posture-right-lateral` / `posture-prone` | 四種睡姿，各自靜息呼吸 | 每姿態 ≥60s | `POSTURES` in `scenarios.py` | Table II、E3 (PASS/C2) |
| `transition` | 週期性翻身（在四姿態間切換） | ≥180s，含 ≥4 次翻身 | `"transition"` | E3 (PASS 翻身偵測+門控) |
| `apnea-event` | 插入呼吸中止事件的呼吸紀錄 | ≥180s，含 ≥3 次事件 | `"apnea-event"` | Table III、E4 (C3) |
| ├─ 事件子型 `hypopnea` | 呼吸變淺（非停止），≥10s | 每次事件 ≥10s | `clinical.HYPOPNEA` | 對應動作型偵測會漏判的類別 |
| ├─ 事件子型 `apnea-osa` | 憋氣但胸腹努力持續/加劇（模擬阻塞：捏鼻+閉嘴但做出用力呼吸動作） | 每次事件 ≥10s | `clinical.APNEA_OSA` | 對應動作型偵測會漏判的類別 |
| └─ 事件子型 `apnea-csa` | 完全停止呼吸動作 | 每次事件 ≥10s | `clinical.APNEA_CSA` | 對應動作型偵測抓得到的類別 |
| `walk` / `interference-*` | 走動、風扇、寵物等干擾（非正式評分情境，供對照） | ≥30s | 對應孿生 `INTERF` 情境 | 定性對照，不進 Table |

> 為什麼時長是這些數字：`estimate_rate`／`pass_select.select_sensitive` 的 DFT 需要至少
> ~10–16 秒才能可靠解析呼吸頻率（見 §2.12／`benchmark.py` 的量測）；臨床上一個「可計分事件」
> 定義是 ≥10 秒（`clinical.py` 的 `ahi()` 也用這個門檻）。錄短於這個長度，事後分析會被迫捨棄。

---

## 2. 空間環境紀錄（房間尺寸、Tx/Rx/人 座標、材質）

**這一節常被忽略，但跟情境標記一樣重要**——原因是它跟合成側是直接綁定的：

- **對比驗證**：孿生（twin）匯出的情境 JSON 本來就有一個 `geometry` 區塊（房間寬深、Tx/Rx
  座標、人的位置、家具、牆材質），設計目的就是讓你能**用真實房間的實際尺寸建一個對應的合成
  場景**，做真正的一比一 sim-to-real 比較，而不只是「大致上像不像」。沒有座標，這條路就斷了。
- **E5（跨場域校準）**：驗證的就是「換房間後子載波敏感度改變、需要重新校準」——沒有幾何紀錄，
  連「這兩次錄製是不是同一個空間配置」都無法確認，E5 沒辦法用真實資料重跑。
- **C2/PASS（姿態感知子載波選擇）**：翻身時哪些子載波變敏感，取決於 Tx→Rx 連線方向與人的
  相對位置——沒有座標，事後分析不出「這次翻身偵測為什麼特別準或特別差」。

### 2.1 座標系與量測方式

- **原點**：選房間一個角落當 (0, 0)，+x 沿房間寬度方向、+y 沿房間深度方向（跟孿生 `SPACES`
  的座標慣例一致）。
- **精度**：捲尺量到最近 5cm 即可，**不需要雷射測距儀等級的精度**——這本來就是粗粒度幾何模型
  （多路徑分析用的是公尺級的路徑長度差），量測誤差在這個尺度下不影響結論。
- **記錄什麼**：房間寬 × 深（公尺）、Tx 座標、Rx 座標（若多天線，每支天線都記，或至少記中心
  點＋天線間距/朝向）、人／床中心座標、牆面材質（乾牆/混凝土/玻璃磁磚/木質，對應孿生
  `WALL_MAT` 分類）、主要家具（可略過，但若房間有大型金屬/鏡面物體建議記一筆）。
- **畫法**：手繪一張俯視簡圖（紙上或手機拍照）比純文字座標更不容易出錯，量完直接照張相存進
  `session_id/` 資料夾即可，不強制要求 CAD 等級的圖。

### 2.2 房間類型對照（可用孿生既有分類，或自訂）

| `space_key` | 孿生對應 | 典型尺寸（w×h，公尺） |
|---|---|---|
| `bedroom` | `SPACES.bedroom` | 5×4 |
| `living` | `SPACES.living` | 6×5 |
| `ward` | `SPACES.ward` | 4×3 |
| `car` | `SPACES.car` | 3×2 |
| `custom` | — | 實際量測值，不必套用上述任何一種 |

用既有分類只是方便事後跟孿生預設場景對照；**實際數字一律以現場量測為準**，`custom` 完全沒問題。

---

## 3. 檔案與資料夾命名規範

```
data/
  <subject_id>/
    <session_id>/
      <scenario_key>__<hw>__<YYYYMMDD-HHMMSS>.<ext>      ← 原始擷取檔（FeitCSI/.bin, IWL/.dat, CSV…）
      <scenario_key>__<hw>__<YYYYMMDD-HHMMSS>.manifest.json  ← 見 §4，人工或半自動填寫
      room_layout.jpg / room_layout.txt                   ← §2 的房間手繪圖或座標（每個 session 一份即可，
                                                              除非 Tx/Rx 中途被移動則需分次記錄）
      session.log                                         ← 操作日誌（見 §5）
```

範例：
```
data/S01/2026-07-10_pm/
  room_layout.jpg
  normal-supine__ax211_20mhz__20260710-143205.bin
  normal-supine__ax211_20mhz__20260710-143205.manifest.json
  apnea-event__ax211_20mhz__20260710-144010.bin
  apnea-event__ax211_20mhz__20260710-144010.manifest.json
  session.log
```

`<hw>` 務必寫清楚**工具＋頻寬**（例如 `ax211_20mhz`、`ax211_160mhz`、`esp32_ht20`），因為子載波數
（52／56／114／256…）只看熱圖猜不出來，必須錄製當下就記下來——這正是本文件開頭那次教訓的直接對策。

---

## 4. Manifest（每個錄製檔案一份，JSON）

欄位刻意對齊孿生匯出的 `csi-digital-twin/manifest@1` schema（含 §2 的 `geometry` 區塊）與
`load_real_csi`/`sim_to_real.py` 所需參數，事後串接零轉換；`geometry` 只要 §2 量過一次同一個
`session_id` 內就能重複使用（除非中途移動了 Tx/Rx/人）。

```json
{
  "schema": "real-capture/manifest@1",
  "subject_id": "S01",
  "session_id": "2026-07-10_pm",
  "scenario_key": "apnea-event",
  "hardware": { "tool": "FeitCSI", "chipset": "AX211", "band_mhz": 20, "channel": 11,
                "n_subcarriers_expected": 52, "n_rx_antennas": 2 },
  "capture": { "file": "apnea-event__ax211_20mhz__20260710-144010.bin",
               "start_wallclock": "2026-07-10T14:40:10+08:00", "duration_s": 190,
               "time_scale_to_seconds": 1.0 },
  "geometry": {
    "space_key": "bedroom", "width_m": 4.8, "depth_m": 3.6,
    "tx_m": [0.6, 2.0], "rx_m": [4.2, 2.0], "rx_antennas_m": [[4.2, 1.97], [4.2, 2.03]],
    "person_m": [2.4, 2.0], "wall_material": "drywall",
    "furniture": [{ "x": 0.6, "y": 0.5, "r": 0.3, "n": "衣櫃" }],
    "layout_photo": "room_layout.jpg"
  },
  "subject_state": { "posture": "supine", "position_note": "床中央，胸口對 Rx 連線" },
  "ground_truth": {
    "breathing_bpm_nominal": 15,
    "reference_method": "手動計時口述 / 呼吸帶 / 無（僅事件標記）",
    "events": [
      { "type": "apnea-osa", "start_s": 42.0, "end_s": 54.0 },
      { "type": "apnea-csa", "start_s": 98.5, "end_s": 110.0 },
      { "type": "hypopnea",  "start_s": 150.0, "end_s": 161.0 }
    ]
  },
  "notes": "42s、60s 附近畫面上有尖銳滿刻度垂直線，需核對是否對應上面的事件時間或是採集缺陷"
}
```

- `n_subcarriers_expected` 讓事後可以立刻核對 `load_real_csi()` 讀出來的 `res.csi.shape[1]`
  是否吻合——不吻合就代表格式辨識錯誤或擷取設定有誤。
- `geometry` 欄位名稱（`width_m`/`depth_m`/`tx_m`/`rx_m`/`rx_antennas_m`/`person_m`/
  `wall_material`/`furniture`）跟孿生匯出的情境 JSON **逐欄位相同**，可以直接把這裡的數字貼進
  孿生介面（空間設定／Tx/Rx 拖曳／牆材質選單）去重建對應的合成場景做並列比較。
- `events` 的時間軸是**相對錄製起點的秒數**（不是絕對時鐘），跟 `clinical.ClinicalEvent(kind, start, duration)`
  的表示法一致，方便直接比對合成側的 `apnea-event` 情境。
- `reference_method` 誠實填「無」也沒關係——沒有真值仍可用來看**偵測率/SNR_eff**（見 §6），
  只是不能算 BPM 誤差。

---

## 5. 錄製操作檢查清單（`session.log` 每次錄製前過一遍）

- [ ] **硬體/頻寬/頻道**已確認並寫進檔名與 manifest（`iw dev wlan0 info` 核對）
- [ ] **房間尺寸、Tx/Rx/人座標已量測並記錄**（§2；同一 session 內 Tx/Rx 沒動過就不必重量，
  但若中途調整過位置，務必補記一份新的 `geometry`）
- [ ] 房間內**除受試者外無其他人員走動**（除非該次就是要錄干擾情境）
- [ ] 錄製開始時**大聲報時**或用手機碼表對錶（供事後對照 `session.log` 的事件時間）
- [ ] 每個呼吸中止/低通氣事件，操作者**當場記錄「開始秒數／結束秒數／類型」**（不要事後回想）
- [ ] 錄製結束後**立刻**填 manifest（人腦記憶會在幾分鐘內失真）
- [ ] 錄完當場跑一次 §6 的 `load_real_csi` 檢查——**子載波數、封包數是否合理**，不合理就重錄
  （比事後才發現省事得多）

---

## 6. 收集完後怎麼接進管線

```python
from csi_synth import load_real_csi, estimate_rate

res = load_real_csi("data/S01/2026-07-10_pm/normal-supine__ax211_20mhz__20260710-143205.bin")
print(res.csi.shape)          # 核對是否等於 manifest 的 n_subcarriers_expected
print(estimate_rate(res, band=(0.1, 0.6))["bpm"])
```

`load_real_csi` 會自動辨識檔案格式：`.bin`／CSIKit 支援的格式（FeitCSI/AX211、IWL、Nexmon）
走 CSIKit；若是 `Timestamp,Sub_0..Sub_N` 這種每列一個封包、逐子載波振幅的 CSV（目前學生端
ESP32-CSI-tool 匯出的實際格式），會自動改走內建的 `load_amplitude_csv`，不需要裝 CSIKit，也
不會有相位資訊（`label["phase_available"] is False`，`estimate_rate`／PASS 用振幅一樣可跑）。
`sample_rate` 一律從時間戳量測，**不要假設任何固定值**——目前量到的 ESP32 實測擷取率約
6 Hz，遠低於本專案模擬端預設的 20 Hz，若程式其他地方（例如自寫的分析腳本）沒有把量到的
`res.config.sample_rate` 帶進 `pass_select` 系列函式，頻率估計會整批錯誤且不會報錯，务必留意。

或直接產出 sim-to-real 對比報表：

```bash
python sim_to_real.py data/S01/.../normal-supine__ax211_20mhz__20260710-143205.bin \
  --truth-bpm 15
```

若該情境有匹配的孿生合成匯出（用相同 seed/設定產生，見 §2.8；`geometry` 直接用 §2 量到的數字
在孿生介面重建同一個房間），可以並列比較：

```bash
python sim_to_real.py <real.bin> --truth-bpm 15 \
  --sim-csi twin_bedroom_breathe_seed12345.csv --sim-manifest twin_bedroom_breathe_seed12345.json
```

**對應論文位置**：`normal-supine`／四姿態結果 → Table I/II（呼吸率 MAE，對應 E1）；
`apnea-event` 結果（`sim_to_real` 的偵測率＋分型準確度）→ Table III（對應 E4/C3，與
`dual_task_analysis.py` 的合成基準並列）；`transition` 結果 → PASS 消融（對應 E3/C2，與
`pass_analysis.py` 的合成基準並列）；**跨多個 `geometry` 不同的 session** → E5 跨場域校準
（對應 `site_calibration.py` 的合成基準）。**用同一支腳本、同一組指標欄位**，真實列直接接在
合成列旁邊即可成表。

---

## 7. 常見陷阱（來自實際案例，事後排查用）

- **中間一條完全平坦的水平帶**：正常，是 OFDM DC null 子載波＋guard band，不是資料遺失
  （對照孿生 `ofdmMask`／§2.8）。
- **單一 frame 寬、幾乎打滿刻度的垂直尖峰**：先查 `session.log` 該時間點是否對應到記錄的事件；
  若沒有對應事件，很可能是封包遺失後插值或 AGC 跳動的採集缺陷（對照 §2.7 的 `ACQ` 模型），
  記在 manifest 的 `notes` 裡，分析時可考慮遮罩排除。
- **全頻段同步暴衝、涵蓋多個子載波**：這是大幅肢體動作，不是呼吸——呼吸應該只在少數敏感
  子載波上有小振幅、緩慢週期的擾動。如果目標是錄呼吸卻看到這種暴衝，代表受試者當下在動，
  該段不能拿來當呼吸率真值對照。
- **子載波數與硬體設定對不上**：回頭核對 `iw dev` 的頻寬設定與 FeitCSI 版本，52／56／114／256
  分別對應不同頻寬設定，不要用肉眼猜。
- **沒記房間幾何，事後想比對合成資料卻做不到**：見 §2——這是本文件新增的一節，正是為了避免
  這個狀況。已經錄好但沒記幾何的舊資料，至少事後補記「房間類型＋大約尺寸＋人相對 Tx/Rx 哪一側」，
  好過完全沒有。
- **`load_real_csi` 讀學生端 CSV 沒報錯，但 `res.csi.shape` 是 0 或內容全錯**：這是已修好的真實
  案例——CSIKit 的 `get_reader()` 不認得 `Timestamp,Sub_0..Sub_N` 這種振幅 CSV，會誤判成 Intel
  binary 格式，印一堆 `Invalid code for beamforming measurement` 然後回傳 0 frame（不會丟
  exception，很容易被忽略）。`load_real_csi` 現在會先檢查檔頭是否符合這個 CSV schema，符合就直接
  走內建解析器，不會誤入 CSIKit；如果自己另外寫腳本繞過 `load_real_csi` 直接呼叫 CSIKit，記得先
  用 `csi_synth.realdata._looks_like_amplitude_csv()` 判斷檔案格式。
- **空房間／無人録製也量到「呼吸率」**：`estimate_rate` 只要頻譜在呼吸頻段有峰值就會回報一個
  BPM 數字，不會自己判斷房間到底有沒有人。用 `fused_snr_eff` 搭配 §2 的空間紀錄一起看：目前在
  ESP32 實測空房間資料上量到的 `fused_snr_eff` 落在 1.5–2 附近（噪聲層級），明顯低於有人走動時
  段（約 4，但那多半是動作洩漏到呼吸頻段而非真的呼吸訊號）；在還沒有一段「有人平躺、安靜、
  有 ground-truth 呼吸率」的錄製之前，不要把任何一段的 `estimate_rate` 輸出當成呼吸率真值。

---

*DofLab · 國立勤益科技大學 · 智慧自動化工程系*
