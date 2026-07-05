"""
test_site_calibration.py — E5 cross-site calibration experiment validation.

Locks in the layered-calibration story at low SNR:
  * site-specific subcarrier selection beats a generic (cross-room) model and
    reaches the oracle bound,
  * few-shot calibration recovers most of that gain,
  * the calibrated model is FRAGILE: moving the sensor/furniture breaks it,
  * re-calibrating on the changed room restores accuracy.
These orderings are deterministic (seeded) and are the E5 result for the paper.

Run:  python -m pytest tests/test_site_calibration.py -v
"""
from __future__ import annotations
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import site_calibration as SC


def test_site_calibration_ordering():
    r = SC.run_experiment()
    # site-specific clearly beats generic, and reaches ~oracle
    assert r["site"] < r["generic"] - 1.0
    assert r["site"] <= r["oracle"] + 0.3
    # few-shot recovers most of the gain (between generic and site)
    assert r["fewshot"] < r["generic"] - 0.5
    assert r["fewshot"] <= r["site"] + 0.6
    # fragility: a sensor/furniture move breaks the stale site model
    assert r["site_moved"] > r["site"] + 0.5
    # re-calibration on the changed room restores accuracy
    assert r["recal"] < r["site_moved"] - 0.5
    assert r["recal"] <= r["site"] + 0.3


if __name__ == "__main__":
    test_site_calibration_ordering()
    print("E5 site-calibration test: OK")
