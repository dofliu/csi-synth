# csi_synth — 合成 WiFi CSI 生成器（數位孿生）

在取得真實 Intel AX211 硬體數據**之前**，用物理模型生成帶標籤的合成 CSI，
讓分析管線（前處理 → 特徵 → 模型）可以先建起來並測試。

> ⚠️ **學術誠實原則**：合成 CSI 僅用於管線開發與演算法驗證。
> 任何用合成資料訓練的模型，**必須**在真實擷取的 CSI 上重新驗證。
> 絕不可將合成結果當作實驗量測值報告。

---

## 設計理念

物理正確的核心（乾淨訊號）+ 可選的雜訊層（真實感），分離設計：

```
geometry.py   →  房間幾何、多路徑路徑長度（影像源法）
generator.py  →  複數 CSI 生成（OFDM 子載波 × 時間），乾淨無雜訊
noise.py      →  可選的硬體損傷層（AWGN / CFO / SFO / AGC / 相位抖動）
estimate.py   →  簡單透明的呼吸率估測（帶通 + DFT），用於驗證
scenarios.py  →  批次情境生成（對應論文第四章資料採集矩陣）
```

核心物理方程式：`Δφ = 4π·Δd / λ`
呼吸胸腔起伏調變散射路徑長度 → CSI 相位/振幅週期變化 → DFT 還原呼吸率。

---

## 安裝

```bash
pip install numpy scipy matplotlib
# 套件本身純 Python，直接匯入即可
```

---

## 快速開始

```python
from csi_synth import Room, Node, Person, RadioConfig, generate_csi
from csi_synth import NoiseConfig, apply_noise, estimate_rate

# 房間 5×4 m，Tx/Rx 對向，人在中間呼吸 15 BPM
room = Room(5, 4)
tx, rx = Node(0.6, 2.0), Node(4.4, 2.0)
person = Person(2.5, 2.0, breathing={"rate_bpm": 15, "amplitude_mm": 5})

# 生成乾淨 CSI（30 秒）
clean = generate_csi(room, tx, rx, person, duration=30)

# 加上真實感雜訊
noisy = apply_noise(clean, NoiseConfig(snr_db=25, cfo_hz=200, sfo_ppm=5))

# 驗證：估測呼吸率
est = estimate_rate(noisy, band=(0.1, 0.6))
print(f"估測呼吸率：{est['bpm']:.2f} BPM")   # ≈ 15.0
```

輸出的 `CSIResult.csi` 是複數陣列，形狀 `(n_time, n_subcarriers)`，
可直接餵給 CSIKit 相容的前處理流程。

---

## 情境批次生成

對應論文第四章的資料採集情境矩陣：

```python
from csi_synth import make_scenario, build_dataset, NoiseConfig

# 單一情境
apnea = make_scenario("apnea-event", duration=90,
                      noise=NoiseConfig(snr_db=25))
mask = apnea.label["apnea_mask"]   # 逐時的呼吸中止真值標籤

# 一次生成全部情境
dataset = build_dataset(duration=30, noise=NoiseConfig(snr_db=25))
```

支援情境：
| 情境 | 說明 | 標籤 |
|---|---|---|
| `baseline` | 空房間（無人） | baseline |
| `normal-supine` | 仰臥正常呼吸 | br_bpm |
| `posture-{supine/left-lateral/right-lateral/prone}` | 四種睡姿 | posture |
| `transition` | 週期性翻身（姿態轉換） | segments |
| `apnea-event` | 插入 10 秒憋氣段的呼吸中止 | apnea_mask |

---

## 驗證測試

```bash
python tests/test_validation.py        # 簡易報告
python -m pytest tests/ -v             # 完整測試
```

驗證證明的核心命題：**設定什麼呼吸率，就能還原出什麼呼吸率**。
乾淨訊號誤差 < 0.05 BPM，含雜訊 < 1 BPM，跨 56/114/256 子載波皆成立。

---

## 視覺化

```bash
python demo_visualize.py    # 生成 csi_synth_demo.png（四面板圖）
```

---

## 雜訊模型參數（NoiseConfig）

| 參數 | 說明 | 真實對應 |
|---|---|---|
| `snr_db` | 目標信雜比 | 熱雜訊 / 接收機雜訊 |
| `cfo_hz` | 載波頻率偏移 | 時間軸線性相位漂移 |
| `sfo_ppm` | 取樣頻率偏移 | 子載波間相位斜率 |
| `agc_std` | 自動增益漂移 | AGC 慢速增益波動 |
| `phase_jitter_std` | 相位抖動 | 每封包隨機相位 |

調高雜訊 → 測試前處理與模型的魯棒性。
調至 0 → 純物理驗證。

---

## 姿態感知子載波選擇 PASS（貢獻 C2）

```python
from csi_synth import (learn_posture_profiles, PASSTracker,
                       detect_transitions, select_sensitive)

# 1) 每姿態學一份 profile（乾淨校準）：指紋 + 敏感子載波
profiles = learn_posture_profiles({posture: amp_windows, ...}, k=6)
# 2) 線上：偵測翻身 → 分類姿態 → 重選子載波 → 估呼吸率
turns = detect_transitions(amp, fs=20.0)
tracker = PASSTracker(profiles=profiles, k=6)
out = tracker.estimate(stable_window)     # {posture, subcarriers, bpm, snr_eff}
```

消融實驗：`python pass_analysis.py`（圖 `plot_pass.py` → `pass_results.png`）。誠實結論：
翻身偵測 100%、姿態分類單天線 33%→雙天線 72%（單鏈路無法分左右側臥的鏡像對稱，
AX211 第二天線打破它）、翻身門控把呼吸率 MAE 1.12→0.53；**子載波重選在單鏈路理想
模型增益僅 ~3%（與高維分集結論一致），真正增益待真實 MIMO 驗證**。

---

## 互動數位孿生的匯出橋接（twin_import）

互動數位孿生 `csi-digital-twin-pro.jsx` 可匯出兩個檔案，用於和真實 AX211 一對一對比：

- **CSI 視窗 CSV**：`t_s, I0..I{N-1}, Q0..Q{N-1}`（每列一封包，複數 CSI 帶有所有模擬損傷；
  版面同 CSIKit `(n_time, n_subcarriers)`）。
- **情境 JSON manifest**：完整設定＋真值＋ PRNG 種子（可重現，可據以佈置相符的真實擷取）。

用同一套估測管線把它讀回來：

```python
from csi_synth import load_twin_csi, resample_uniform, estimate_rate

res = load_twin_csi("csi_bedroom_breathe_seed12345_240f.csv",
                    "twin_bedroom_breathe_seed12345.json")
uniform = resample_uniform(res)                 # 真實 CSI 非均勻採樣，先補到均勻格點
est = estimate_rate(uniform, band=(0.1, 0.6))
print(est["bpm"], "vs truth", res.label["ground_truth"])
```

或直接：`python -m csi_synth.twin_import <csi.csv> [manifest.json]`

> 孿生的隨機種子固定後，整段合成擷取逐幀可重現——這是「模擬可與真實實驗對比驗證」的前提。

---

## 下一步：接上真實硬體

當 AX211 開始輸出真實 CSI 後：
1. 用 CSIKit 解析真實 `.bin` → 同樣的 `(n_time, n_subcarriers)` 複數陣列
2. 把真實資料接到同一套 `estimate_rate` / 前處理管線（孿生匯出走 `load_twin_csi` 進同一管線）
3. 比較合成 vs 真實的差距，量化 Sim-to-Real Gap
4. 用真實資料重新訓練與驗證模型

DofLab · 國立勤益科技大學 · 智慧自動化工程系
