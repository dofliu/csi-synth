# 第二批真實資料 · 新臥室環境（2026-07-22, ESP32 / 52 子載波）

學生換到一個**接近真實臥室**的環境（有床、桌、櫃、窗簾、冷氣），並把 ESP32 的送包率
大幅拉高。這批的價值是暴露了一個**擷取層面的關鍵問題**，同時第一次拿到可用的完整房間幾何。

## 檔案

| 檔案 | 情境 | frames | 中位數率 | 有效率 | 爆發式? |
|---|---|---|---|---|---|
| `CSI_new_clean_room_20260722_170000.csv` | 空房 baseline A | 37397 | 111 Hz | 63 Hz | 是 |
| `CSI_new_clean_room_2_20260722_171353.csv` | 空房 baseline B | 35563 | 111 Hz | 64 Hz | 是 |
| `CSI_breathe_20260722_172613.csv` | 坐姿呼吸 1 | 3911 | 125 Hz | 64 Hz | 是 |
| `CSI_breathe_2_20260722_172808.csv` | 坐姿呼吸 2 | 4047 | 125 Hz | 66 Hz | 是 |

- 格式同前：`Timestamp,Sub_0..Sub_51` 振幅 CSV，null band 在 23–31。
- 受試者為**坐姿**（坐在桌前椅子上），非平躺。

## 關鍵發現：高採樣率是假象——爆發式非均勻取樣

`load_amplitude_csv` 現在會偵測並警告這個狀況（`realdata.py`，新增 `_sampling_stats`）：
封包間隔中位數 8 ms（看似 111–125 Hz），但 Δt 標準差比平均還大（cv≈1.3），有效平均率只有
~63 Hz。若把它當均勻取樣直接丟進 `estimate_rate`，呼吸峰會塌到 0.1 Hz 頻帶邊緣（假的 6 bpm）。

**正確處理**：先 `resample_uniform()` 到均勻網格再估頻。修正後峰值移到合理的 14–19 bpm。
見 `figs/diag_bursty_sampling.png`。

### 但誠實說：修正後訊號仍不夠乾淨

重取樣後 fused SNR_eff：空房 2.10/2.35、breathe 2.01/2.16——**breathe 沒有勝過空房間**。
對比第一批夜間的 6 Hz **均勻** 捕捉（breathe 2.3–3.3 vs 空房 1.5–2，清楚勝出），
**均勻取樣比高採樣率更重要**。可能原因：爆發式取樣（首要）、坐姿且椅子離 Tx-Rx 連線約 126 cm
（耦合較弱）、呼吸較淺。

## 幾何（第一次完整）→ 數位孿生對比

原點左下角，單位 cm：房間 365(x)×325(y)×305(z)，Rx ESP32=(35,105,80)，Tx N300=(277,45,180)，
3D LoS = 268.6 cm。`twin_new_room.py` 用專案的物理套件（JSX 孿生的同一套核心）依此幾何模擬坐姿
呼吸，並用學生工具同樣的 3 步驟分析並列對比（`figs/twin_vs_real.png`）：**乾淨均勻取樣的孿生**
回收出清楚的單一呼吸峰（真值 16 bpm 準確回收）；**真實爆發式資料**則峰不明顯。這具體示範了
「乾淨均勻擷取應該長什麼樣」。

## 重現

```bash
cd csi_synth
PYTHONPATH=. python real_data/second_batch_20260722/analyze_second_batch.py   # diag_bursty_sampling.png
PYTHONPATH=. python real_data/second_batch_20260722/twin_new_room.py          # twin_vs_real.png
```

## 待補（同前）

- **Ground-truth 呼吸率**：仍未用碼表數，還不能算絕對誤差填 Table I。
- **擷取改成穩定均勻送包**（哪怕 10–20 Hz，只要 Δt 穩定）。
- 受試者位置：建議坐/躺在 Tx-Rx 連線附近以提高耦合。

`manifest.json` 記錄了本批的幾何與情境（欄位對齊 `EXPERIMENT_PROTOCOL.md` §2 的 geometry schema）。

*DofLab · 國立勤益科技大學 · 智慧自動化工程系*
