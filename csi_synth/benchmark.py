"""
benchmark.py — Consolidated performance benchmark for the csi_synth pipeline.

Where the E-experiments isolate one MECHANISM each (E1 diversity, C2 posture,
C3 events, E5 site), this sweeps the OPERATING ENVELOPE end-to-end and records
one results table: how well does vital-sign sensing work across

    hardware (ESP32 / AX210 / AX211)  ×  SNR  ×  scenario (supine / posture)
    ×  realism (ideal point-scatter / full physical layer)

For each cell it runs N seeds × a few breathing rates and records:
    * rate_mae     — breathing-rate error (BPM), fused over the top-K subcarriers
    * detect_rate  — fraction of windows whose breathing is above the detection
                     floor (fused breathing SNR_eff over threshold)
It also reports each device's DETECTION FLOOR (lowest SNR with ≥90% detection).

Reproducible (seeded). Outputs a summary dict; benchmark.py --csv writes
benchmark_results.csv; plot_benchmark.py renders benchmark_results.png.

Honesty: SYNTHETIC — the ORDERINGS (more SNR → lower error; wideband fusion
lowers the detection floor; the physical layer is harder than the ideal model)
are the results; absolute numbers need real AX211 confirmation.
"""
from __future__ import annotations
import sys, os
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from csi_synth import (Room, Node, Person, RadioConfig, generate_csi,
                       NoiseConfig, apply_noise, RealismConfig, RespirationModel)
from csi_synth.realism import generate_csi_realistic
from csi_synth import pass_select as PS

FS = 20.0
DUR = 16.0
DETECT_THR = 2.0                 # fused breathing SNR_eff above which we call it detected
TOP_K = 6

HARDWARE = {"ESP32": 56, "AX210": 114, "AX211": 256}
SNRS = [4, 8, 12, 16, 24]
SCENARIOS = ["supine", "posture"]
REALISM = ["ideal", "physical"]
RATES = [13.0, 17.0]
POSTURES = [(0.0, 0.0), (-0.10, 0.24), (0.10, -0.24), (0.02, 0.14)]

_ROOM = Room(5.0, 4.0)
_TX, _RX = Node(0.6, 2.0), Node(4.4, 2.0)
_BED = (2.5, 2.0)


def _window(n_sub, scenario, realism, rate, snr, seed):
    """One breathing window under the given condition → amplitude (T, n_sub)."""
    cfg = RadioConfig(n_subcarriers=n_sub, sample_rate=FS)
    rng = np.random.default_rng(seed)
    dx, dy = POSTURES[int(rng.integers(len(POSTURES)))] if scenario == "posture" else (0.0, 0.0)
    bx, by = _BED[0] + dx, _BED[1] + dy
    if realism == "physical":
        resp = RespirationModel(rate_bpm=rate, amplitude_mm=5.0, seed=seed)
        rc = RealismConfig(extended_body=True, diffuse=True, rician_k_db=6.0,
                           background_motion=True, seed=seed)
        res = generate_csi_realistic(_ROOM, _TX, _RX, (bx, by), resp, rc, duration=DUR, radio=cfg)
    else:
        person = Person(bx, by, breathing={"rate_bpm": rate, "amplitude_mm": 5.0})
        res = generate_csi(_ROOM, _TX, _RX, person, duration=DUR, config=cfg)
    res = apply_noise(res, NoiseConfig(snr_db=snr, cfo_hz=150, sfo_ppm=4, agc_std=0.03, seed=seed))
    return res.amplitude


def _eval_window(amp, rate):
    subs = PS.select_sensitive(amp, k=TOP_K, fs=FS)
    bpm = PS.estimate_rate_subs(amp, subs, fs=FS)
    snr_eff = PS.fused_snr_eff(amp, subs, fs=FS)
    return abs(bpm - rate), snr_eff >= DETECT_THR


def run_benchmark(hardware=None, snrs=None, scenarios=None, realism=None,
                  seeds=6, rates=None, verbose=False):
    hardware = hardware or HARDWARE
    snrs = snrs or SNRS
    scenarios = scenarios or SCENARIOS
    realism = realism or REALISM
    rates = rates or RATES

    rows = []
    s = 1000
    for hw, n_sub in hardware.items():
        for scen in scenarios:
            for real in realism:
                for snr in snrs:
                    errs, dets = [], []
                    for _ in range(seeds):
                        for rate in rates:
                            amp = _window(n_sub, scen, real, rate, snr, seed=s); s += 1
                            e, d = _eval_window(amp, rate)
                            errs.append(e); dets.append(d)
                    errs = np.array(errs); dets = np.array(dets)
                    # rate MAE is meaningful only where breathing is DETECTED — a rate
                    # you can't detect isn't a reading. detect_rate carries the coverage.
                    if dets.any():
                        de = errs[dets]
                        rate_mae, rate_std = float(de.mean()), float(de.std())
                    else:
                        rate_mae = rate_std = float("nan")
                    rows.append(dict(
                        hardware=hw, n_sub=n_sub, scenario=scen, realism=real, snr_db=snr,
                        n=len(errs), n_detected=int(dets.sum()),
                        rate_mae=rate_mae, rate_std=rate_std,
                        detect_rate=float(np.mean(dets))))
    floors = _detection_floors(rows, hardware, snrs)
    result = dict(rows=rows, floors=floors, snrs=snrs)
    if verbose:
        _print_report(result)
    return result


def _detection_floors(rows, hardware, snrs):
    """Lowest SNR at which a device reaches >=90% detection (supine/ideal)."""
    floors = {}
    for hw in hardware:
        floor = None
        for snr in sorted(snrs):
            cell = [r for r in rows if r["hardware"] == hw and r["snr_db"] == snr
                    and r["scenario"] == "supine" and r["realism"] == "ideal"]
            if cell and cell[0]["detect_rate"] >= 0.9:
                floor = snr; break
        floors[hw] = floor
    return floors


def _print_report(res):
    print("=" * 78)
    print(" csi_synth consolidated benchmark — vital-sign sensing across conditions")
    print("=" * 78)
    print(f"\n {'hardware':<9}{'scenario':<9}{'realism':<10}" +
          "".join(f"{s:>3}dB" for s in res["snrs"]) + "   metric")
    print(" " + "-" * 74)
    for hw in HARDWARE:
        for scen in SCENARIOS:
            for real in REALISM:
                cells = {r["snr_db"]: r for r in res["rows"]
                         if r["hardware"] == hw and r["scenario"] == scen and r["realism"] == real}
                if not cells:
                    continue
                mae = "".join((f"{cells[s]['rate_mae']:>5.1f}" if not np.isnan(cells[s]['rate_mae'])
                               else "    —") for s in res["snrs"] if s in cells)
                det = "".join(f"{cells[s]['detect_rate']*100:>5.0f}" for s in res["snrs"] if s in cells)
                print(f" {hw:<9}{scen:<9}{real:<10}{mae}   rate MAE (BPM)")
                print(f" {'':<9}{'':<9}{'':<10}{det}   detect %")
    print("\n Detection floor (lowest SNR with ≥90% detection, supine/ideal):")
    for hw, fl in res["floors"].items():
        print(f"   {hw:<9} {fl if fl is not None else '>max'} dB")
    print("\n Reading: rate error falls as SNR rises; the wider-band device sustains")
    print(" detection to lower SNR (more subcarriers to fuse); the physical-realism")
    print(" layer is uniformly harder than the ideal point-scatter model.")
    print(" [synthetic — orderings are the result; absolutes need real AX211]")


def _write_csv(res, path):
    cols = ["hardware", "n_sub", "scenario", "realism", "snr_db", "n", "n_detected",
            "rate_mae", "rate_std", "detect_rate"]
    lines = [",".join(cols)]
    for r in res["rows"]:
        lines.append(",".join(str(r[c]) for c in cols))
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {path} ({len(res['rows'])} rows)")


if __name__ == "__main__":
    res = run_benchmark(verbose=True)
    if "--csv" in sys.argv:
        _write_csv(res, os.path.join(os.path.dirname(__file__), "benchmark_results.csv"))
