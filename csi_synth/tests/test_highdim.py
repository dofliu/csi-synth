"""
test_highdim.py — E1 high-dimensional sensitivity experiment validation.

Locks in the physically-required ordering: a 160 MHz / 256-subcarrier device
(AX211) does not mainly win at FINDING one good subcarrier (narrowband devices
manage that too), but at collecting many more INDEPENDENT sensitive frequency
looks — which is what feeds the fused SNR_eff. The ordering follows directly
from sampling S(f) across a wider band, so it is stable across Monte-Carlo draws.

Run:  python -m pytest tests/test_highdim.py -v
"""
from __future__ import annotations
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import highdim_analysis as H


def test_highdim_ordering():
    s = H.run_experiment(n_geom=80, seed=0)
    d5300, desp, dax = s["Intel 5300"], s["ESP32"], s["AX211 (6E)"]

    # (1) narrowband devices DO usually find a decent single subcarrier
    assert d5300["best_of_k"] > 0.85 and desp["best_of_k"] > 0.85
    assert dax["best_of_k"] >= max(d5300["best_of_k"], desp["best_of_k"]) - 1e-6

    # (2) the real gain: AX211 gathers many more INDEPENDENT looks (~8x band)
    assert dax["independent_looks"] > 3 * d5300["independent_looks"]
    assert dax["independent_looks"] > 3 * desp["independent_looks"]

    # (3) which cashes out as several dB more fusion SNR_eff
    adv = s["_ax211_fusion_advantage_db"]
    assert adv["Intel 5300"] > 5.0 and adv["ESP32"] > 5.0

    # (4) no device is often fully blind at this threshold in rich multipath
    for dev in (d5300, desp, dax):
        assert dev["p_blind"] < 0.1


if __name__ == "__main__":
    test_highdim_ordering()
    print("E1 highdim test: OK")
