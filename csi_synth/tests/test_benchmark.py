"""
test_benchmark.py — consolidated benchmark ordering checks.

Locks the operating-envelope results: high-SNR detection saturates and rate error
is small; detection improves with SNR; a wider-band device is more robust at low
SNR; and the full physical-realism layer is harder than the ideal model.

Run:  python -m pytest tests/test_benchmark.py -v
"""
from __future__ import annotations
import sys, os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import benchmark as B


def _cell(rows, hw, snr, real="ideal", scen="supine"):
    c = [r for r in rows if r["hardware"] == hw and r["snr_db"] == snr
         and r["realism"] == real and r["scenario"] == scen]
    return c[0] if c else None


def test_benchmark_orderings():
    res = B.run_benchmark(hardware={"ESP32": 56, "AX211": 256}, snrs=[8, 24],
                          scenarios=["supine"], realism=["ideal", "physical"],
                          seeds=5, rates=[15.0])
    rows = res["rows"]

    # high-SNR ideal: breathing fully detected and accurately estimated
    for hw in ("ESP32", "AX211"):
        hi = _cell(rows, hw, 24, "ideal")
        assert hi["detect_rate"] == 1.0
        assert hi["rate_mae"] < 1.5
        # detection improves (or holds) from low to high SNR
        lo = _cell(rows, hw, 8, "ideal")
        assert hi["detect_rate"] >= lo["detect_rate"]

    # wider band is at least as robust at low SNR
    assert _cell(rows, "AX211", 8, "ideal")["detect_rate"] >= \
           _cell(rows, "ESP32", 8, "ideal")["detect_rate"]

    # the physical-realism layer is harder than the ideal model (lower detection)
    ideal = np.mean([r["detect_rate"] for r in rows if r["realism"] == "ideal"])
    phys = np.mean([r["detect_rate"] for r in rows if r["realism"] == "physical"])
    assert phys < ideal


if __name__ == "__main__":
    test_benchmark_orderings()
    print("benchmark test: OK")
