# 首批真實 CSI 資料 · 2026-07-21（ESP32 / 52 子載波）

這是本專案第一批接上管線的**真實**擷取資料，由學生在校內一間工具/儲藏空間錄製。
用途是**把 sim→real 管線與偵測器在真實硬體上跑通**，尚不是可填論文 Table 的計分資料。

## 檔案

| 檔案 | 情境 | frames | 時長 | 實測 fs |
|---|---|---|---|---|
| `CSI_clean_room_20260721_020546.csv` | 空房間 baseline A | 3578 | 585 s | 6.10 Hz |
| `CSI_clean_room_20260721_021822_trimmed.csv` | 空房間 baseline B | 3848 | 627 s | 6.10 Hz |
| `CSI_in_room_20260721_023127.csv` | 坐著滑手機 → 走動（動作測試） | 2767 | 450 s | 6.10 Hz |

- **格式**：`Timestamp,Sub_0..Sub_51` 振幅 CSV（無相位），時戳 `HH:MM:SS.mmm`。由
  `csi_synth.load_real_csi()` 自動辨識並解析（見 `realdata.py`／`EXPERIMENT_PROTOCOL.md`）。
- **硬體推斷**：52 子載波 + subcarrier 23–31（9 個）固定全零的 null/guard band → ESP32-CSI-tool
  HT20（**非**論文主打的 AX211/256 子載波）。
- **空間**：堆滿雜物的工具/儲藏間，金屬置物櫃為強反射體 → 幾何記為 `custom`。**不是臥室**，
  正式計分錄製建議換到乾淨、有床的空間，或明確記錄此環境為預期部署場域。

## 重現分析圖

```bash
cd csi_synth
PYTHONPATH=. python real_data/first_batch_20260721/analyze_first_batch.py
```

產生 `figs/fig1..fig4`（全部用專案自己的 `load_real_csi` / `pass_select`）。

## 關鍵發現

1. **採樣率必須量測**：實測 6.1 Hz，遠低於程式各處預設的 20 Hz。呼吸（≤0.6 Hz，Nyquist 1.2 Hz）
   還夠用，但心跳與細緻頻譜偏低，建議調 ESP32-CSI-tool 送包設定拉高。（圖2）
2. **偵測器正向驗證**：純用合成資料調校的 `detect_transitions` 正確定位到 in_room 檔的走動事件
   （~290–360 s，圖1 熱圖清楚可見結構重組）。（圖1、圖3）
3. **空房間誤報 5.9% / 9.0%**：偵測閾值套到真實場域偏鬆。調高閾值（＝學到本場域雜訊層級）可降到
   ~2–3.4%，但有地板，光靠純量閾值降不到 0——需要學本場域的空間/頻譜背景模型（論文 C4 場域校準）。
   **每個新場域先錄一段空房間 baseline 當校準資料**。（圖4A）
4. **呼吸頻段 SNR**：兩份空房間 fused SNR_eff ~1.5–2（雜訊層級），走動那份 ~4.0 是動作能量洩漏，
   **不是呼吸**。三份都沒有「有人平躺安靜＋GT 呼吸率」的區段，故此批不宣稱任何呼吸率準確度。（圖4B）

## 下一步（要能填 Table I–IV）

需要一段 **`normal-supine`**：人平躺不動、正常呼吸 ≥30–60 s，同步用碼表數呼吸次數記 ground-truth
BPM，並照 `EXPERIMENT_PROTOCOL.md` §2 記房間幾何；同場域再錄一段空 baseline 供校準。到位後
`python sim_to_real.py <capture.csv> --truth-bpm N` 即可產出真實 vs 合成對比。

*DofLab · 國立勤益科技大學 · 智慧自動化工程系*
