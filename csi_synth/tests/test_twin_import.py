"""
test_twin_import.py — Round-trip test for the interactive digital-twin export.

Proves the sim-to-real BRIDGE: CSI written in the twin's export format
(t_s, I0.., Q0..) + a manifest, loaded back via load_twin_csi, and run through
the SAME estimate_rate used for real AX211 data, recovers the ground-truth
breathing rate — even with non-uniform sampling (timestamp jitter + packet loss).

Run:  python -m pytest tests/test_twin_import.py -v
"""
from __future__ import annotations
import csv, json, os, sys, tempfile
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from csi_synth import (
    Room, Node, Person, RadioConfig, generate_csi,
    load_twin_csi, resample_uniform, estimate_rate,
)


def _write_twin_export(dirpath, br_bpm=15.0, n_sub=64, sr=20.0, duration=40.0,
                       loss=0.08, ts_jit=0.35, seed=0):
    """Emit a (csi.csv, manifest.json) pair in the twin's export format."""
    room = Room(5, 4)
    tx, rx = Node(0.6, 2.0), Node(4.4, 2.0)
    person = Person(2.5, 2.0, breathing={"rate_bpm": br_bpm, "amplitude_mm": 6})
    cfg = RadioConfig(n_subcarriers=n_sub, sample_rate=sr)
    res = generate_csi(room, tx, rx, person, duration=duration, config=cfg)

    rng = np.random.default_rng(seed)
    keep = rng.random(res.csi.shape[0]) > loss
    csv_path = os.path.join(dirpath, "csi.csv")
    head = ["t_s"] + [f"I{k}" for k in range(n_sub)] + [f"Q{k}" for k in range(n_sub)]
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(head)
        for i in range(res.csi.shape[0]):
            if not keep[i]:
                continue
            ts = res.t[i] + (rng.random() * 2 - 1) * ts_jit / sr
            row = ([round(ts, 4)]
                   + [round(v, 5) for v in res.csi[i].real]
                   + [round(v, 5) for v in res.csi[i].imag])
            w.writerow(row)

    man_path = os.path.join(dirpath, "manifest.json")
    json.dump({
        "schema": "csi-digital-twin/manifest@1", "seed": seed,
        "radio": {"f_center_Hz": 2.437e9, "bandwidth_Hz": 20e6,
                  "n_subcarriers": n_sub, "sample_rate_Hz": sr},
        "ground_truth": {"breathing_bpm": br_bpm, "heart_bpm": None},
    }, open(man_path, "w"), indent=2)
    return csv_path, man_path


def test_twin_roundtrip_recovers_rate():
    """Twin export -> loader -> resample -> estimate recovers BR within 1 BPM."""
    with tempfile.TemporaryDirectory() as d:
        for br in [12.0, 15.0, 18.0]:
            csv_path, man_path = _write_twin_export(d, br_bpm=br)
            res = load_twin_csi(csv_path, man_path)
            assert res.csi.dtype == complex
            assert res.csi.shape[1] == 64
            assert res.label["nonuniform_sampling"] is True
            assert res.label["seed"] == 0
            ru = resample_uniform(res)
            est = estimate_rate(ru, band=(0.1, 0.6))
            err = abs(est["bpm"] - br)
            assert err < 1.0, f"BR={br}: recovered {est['bpm']:.2f}, err {err:.2f}"


def test_twin_loads_without_manifest():
    """CSV alone loads; sample rate is inferred from timestamps."""
    with tempfile.TemporaryDirectory() as d:
        csv_path, _ = _write_twin_export(d, br_bpm=15.0, sr=20.0)
        res = load_twin_csi(csv_path)  # no manifest
        assert 15.0 < res.config.sample_rate < 25.0  # inferred ~20 Hz
        assert res.label["ground_truth"] is None


if __name__ == "__main__":
    test_twin_roundtrip_recovers_rate()
    test_twin_loads_without_manifest()
    print("twin_import round-trip: OK")
