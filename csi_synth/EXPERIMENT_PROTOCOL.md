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
尖峰是走路、干擾還是採集缺陷），最後只能靠「事後猜測」重建情境，**完全無法拿來對比合成資料
或填論文 Table**。

原則很簡單：**錄製當下 3 秒就能寫完的 metadata，事後永遠補不回來。** 本協定就是把這 3 秒鐘
要記的東西定下來。

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

## 2. 檔案與資料夾命名規範

```
data/
  <subject_id>/
    <session_id>/
      <scenario_key>__<hw>__<YYYYMMDD-HHMMSS>.<ext>      ← 原始擷取檔（FeitCSI/.bin, IWL/.dat, CSV…）
      <scenario_key>__<hw>__<YYYYMMDD-HHMMSS>.manifest.json  ← 見 §3，人工或半自動填寫
      session.log                                         ← 操作日誌（見 §4）
```

範例：
```
data/S01/2026-07-10_pm/
  normal-supine__ax211_20mhz__20260710-143205.bin
  normal-supine__ax211_20mhz__20260710-143205.manifest.json
  apnea-event__ax211_20mhz__20260710-144010.bin
  apnea-event__ax211_20mhz__20260710-144010.manifest.json
  session.log
```

`<hw>` 務必寫清楚**工具＋頻寬**（例如 `ax211_20mhz`、`ax211_160mhz`、`esp32_ht20`），因為子載波數
（52／56／114／256…）只看熱圖猜不出來，必須錄製當下就記下來——這正是本文件開頭那次教訓的直接對策。

---

## 3. Manifest（每個錄製檔案一份，JSON）

欄位刻意對齊孿生匯出的 `csi-digital-twin/manifest@1` schema 與 `load_real_csi`/`sim_to_real.py`
所需參數，事後串接零轉換。

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
- `events` 的時間軸是**相對錄製起點的秒數**（不是絕對時鐘），跟 `clinical.ClinicalEvent(kind, start, duration)`
  的表示法一致，方便直接比對合成側的 `apnea-event` 情境。
- `reference_method` 誠實填「無」也沒關係——沒有真值仍可用來看**偵測率/SNR_eff**（見 §5），
  只是不能算 BPM 誤差。

---

## 4. 錄製操作檢查清單（`session.log` 每次錄製前過一遍）

- [ ] **硬體/頻寬/頻道**已確認並寫進檔名與 manifest（`iw dev wlan0 info` 核對）
- [ ] 房間內**除受試者外無其他人員走動**（除非該次就是要錄干擾情境）
- [ ] Tx/Rx 位置、受試者相對位置已記錄（一句話描述即可，如上面 `position_note`）
- [ ] 錄製開始時**大聲報時**或用手機碼表對錶（供事後對照 `session.log` 的事件時間）
- [ ] 每個呼吸中止/低通氣事件，操作者**當場記錄「開始秒數／結束秒數／類型」**（不要事後回想）
- [ ] 錄製結束後**立刻**填 manifest（人腦記憶會在幾分鐘內失真）
- [ ] 錄完當場跑一次 §5 的 `load_real_csi` 檢查——**子載波數、封包數是否合理**，不合理就重錄
  （比事後才發現省事得多）

---

## 5. 收集完後怎麼接進管線

```python
from csi_synth import load_real_csi, estimate_rate

res = load_real_csi("data/S01/2026-07-10_pm/normal-supine__ax211_20mhz__20260710-143205.bin")
print(res.csi.shape)          # 核對是否等於 manifest 的 n_subcarriers_expected
print(estimate_rate(res, band=(0.1, 0.6))["bpm"])
```

或直接產出 sim-to-real 對比報表：

```bash
python sim_to_real.py data/S01/.../normal-supine__ax211_20mhz__20260710-143205.bin \
  --truth-bpm 15
```

若該情境有匹配的孿生合成匯出（用相同 seed/設定產生，見 §2.8），可以並列比較：

```bash
python sim_to_real.py <real.bin> --truth-bpm 15 \
  --sim-csi twin_bedroom_breathe_seed12345.csv --sim-manifest twin_bedroom_breathe_seed12345.json
```

**對應論文位置**：`normal-supine`／四姿態結果 → Table I/II（呼吸率 MAE，對應 E1）；
`apnea-event` 結果（`sim_to_real` 的偵測率＋分型準確度）→ Table III（對應 E4/C3，與
`dual_task_analysis.py` 的合成基準並列）；`transition` 結果 → PASS 消融（對應 E3/C2，與
`pass_analysis.py` 的合成基準並列）。**用同一支腳本、同一組指標欄位**，真實列直接接在合成列
旁邊即可成表。

---

## 6. 常見陷阱（來自實際案例，事後排查用）

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

---

*DofLab · 國立勤益科技大學 · 智慧自動化工程系*
