"""
twin_import.py — Load the interactive digital twin's exported CSI into the
same objects the Python pipeline uses for real AX211 data.

The interactive twin (`csi-digital-twin-pro.jsx`) can export two files:

  1. a CSI window CSV   — columns: t_s, I0..I{N-1}, Q0..Q{N-1}
                          (one row per delivered packet; complex CSI carries
                          every simulated impairment: AWGN, CFO/SFO/AGC, STO,
                          per-subcarrier calibration, packet-loss gaps, null/
                          guard tones). Layout mirrors CSIKit (n_time × n_sub).
  2. a scenario manifest JSON — full config + ground truth + the exact PRNG
                          seed, so the run is reproducible and a matched real
                          capture can be set up for a one-to-one comparison.

This module reconstructs a `CSIResult` from those files so the SAME
`estimate_rate` / preprocessing pipeline can run on twin output and on real
captures — which is what makes the sim-to-real gap measurable (paper Tbl I-IV).

    from csi_synth.twin_import import load_twin_csi
    from csi_synth import estimate_rate

    res = load_twin_csi("csi_bedroom_breathe_seed12345_240f.csv",
                        "twin_bedroom_breathe_seed12345.json")
    est = estimate_rate(res, band=(0.1, 0.6))
    print(est["bpm"], "vs truth", res.label.get("ground_truth"))

IMPORTANT (academic honesty): twin output is SYNTHETIC. It is for pipeline
development and relative comparison only, never reported as measurement.
"""
from __future__ import annotations

import csv
import json
from typing import Optional

import numpy as np

from .generator import RadioConfig, CSIResult, C


def _read_manifest(path: Optional[str]) -> dict:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_twin_csi(csv_path: str, manifest_path: Optional[str] = None) -> CSIResult:
    """
    Reconstruct a CSIResult from a twin CSI-window CSV (+ optional manifest).

    Returns a CSIResult with:
        csi    : complex (n_time, n_subcarriers)  = I + jQ
        t      : the exported per-packet timestamps (NON-uniform if the twin's
                 acquisition-defect layer was on — real CSI is not evenly sampled)
        freqs  : subcarrier frequencies (from the manifest radio block if present,
                 otherwise the standard OFDM grid for the detected width)
        config : RadioConfig (sample_rate from manifest, else inferred from t)
        label  : manifest ground_truth / scenario, plus a nominal_uniform flag
    """
    manifest = _read_manifest(manifest_path)

    # ── parse the CSV (t_s, I0.., Q0..) ──
    with open(csv_path, "r", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        raise ValueError(f"empty CSI file: {csv_path}")
    header = rows[0]
    n_sub = sum(1 for h in header if h.startswith("I"))
    if n_sub == 0 or len(header) != 1 + 2 * n_sub:
        raise ValueError(f"unexpected header (expected t_s + I*n + Q*n): {header[:4]}...")

    data = np.array([[float(v) for v in r] for r in rows[1:] if r], dtype=float)
    if data.size == 0:
        raise ValueError(f"no data rows in {csv_path}")
    t = data[:, 0]
    re = data[:, 1:1 + n_sub]
    im = data[:, 1 + n_sub:1 + 2 * n_sub]
    csi = re + 1j * im

    # ── sample rate: prefer the manifest; else infer from median timestamp step ──
    radio = manifest.get("radio", {})
    fs = radio.get("sample_rate_Hz")
    if not fs:
        dt = np.diff(t)
        dt = dt[dt > 0]
        fs = float(1.0 / np.median(dt)) if dt.size else 20.0

    f_center = radio.get("f_center_Hz", 2.437e9)
    bandwidth = radio.get("bandwidth_Hz", 20e6)
    cfg = RadioConfig(f_center=f_center, bandwidth=bandwidth,
                      n_subcarriers=n_sub, sample_rate=float(fs))
    freqs = cfg.subcarrier_freqs

    label = {
        "source": "digital_twin_export",
        "csv_path": csv_path,
        "manifest_path": manifest_path,
        "ground_truth": manifest.get("ground_truth"),
        "scenario": manifest.get("scenario"),
        "impairments": manifest.get("impairments"),
        "seed": manifest.get("seed"),
        # timestamps are the twin's; if the acq-defect layer was on they are
        # non-uniform. estimate_rate treats fs as uniform, so flag this.
        "nonuniform_sampling": bool(np.std(np.diff(t)) > 1e-6),
        "n_time": int(csi.shape[0]),
    }
    if "overnight" in manifest:
        label["overnight"] = manifest["overnight"]

    return CSIResult(csi=csi, t=t, freqs=freqs, label=label, config=cfg)


def resample_uniform(result: CSIResult, fs: Optional[float] = None) -> CSIResult:
    """
    Return a copy of `result` linearly resampled onto a UNIFORM time grid.

    Real CSI (and the twin's acq-defect layer) is non-uniformly sampled with
    packet-loss gaps; the simple DFT estimator assumes uniform fs. Call this
    first when comparing against the estimator's uniform-sampling assumption.
    """
    fs = float(fs or result.config.sample_rate)
    t = result.t
    t0, t1 = float(t[0]), float(t[-1])
    n = max(2, int(round((t1 - t0) * fs)) + 1)
    tu = t0 + np.arange(n) / fs
    # interpolate real and imaginary parts per subcarrier
    re = np.empty((n, result.csi.shape[1]))
    im = np.empty((n, result.csi.shape[1]))
    for k in range(result.csi.shape[1]):
        re[:, k] = np.interp(tu, t, result.csi[:, k].real)
        im[:, k] = np.interp(tu, t, result.csi[:, k].imag)
    cfg = RadioConfig(f_center=result.config.f_center, bandwidth=result.config.bandwidth,
                      n_subcarriers=result.config.n_subcarriers, sample_rate=fs)
    label = dict(result.label)
    label["resampled_uniform"] = True
    return CSIResult(csi=re + 1j * im, t=tu, freqs=result.freqs, label=label, config=cfg)


if __name__ == "__main__":  # pragma: no cover
    import sys
    if len(sys.argv) < 2:
        print("usage: python -m csi_synth.twin_import <csi.csv> [manifest.json]")
        raise SystemExit(1)
    from .estimate import estimate_rate
    res = load_twin_csi(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    gt = (res.label.get("ground_truth") or {})
    print(f"loaded: {res.csi.shape[0]} frames x {res.csi.shape[1]} subcarriers, "
          f"fs={res.config.sample_rate:.3f} Hz, nonuniform={res.label['nonuniform_sampling']}")
    ru = resample_uniform(res)
    est = estimate_rate(ru, band=(0.1, 0.6))
    print(f"estimated breathing: {est['bpm']:.2f} BPM  (truth={gt.get('breathing_bpm')})")
