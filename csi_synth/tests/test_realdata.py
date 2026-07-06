"""
test_realdata.py — real-capture loader (CSIKit → CSIResult) round-trip.

We don't have a real AX211 file in CI, so we build a CSIKit CSIData carrying a
known breathing modulation (exactly the object every CSIKit reader — FeitCSI/AX211,
IWL, Nexmon, CSV — produces), push it through csidata_to_result, and confirm the
SAME estimator recovers the breathing rate. This validates the sim→real plumbing;
the file-format specifics are CSIKit's job and are exercised when real files arrive.

CSIKit is an optional dependency, so this test skips where it isn't installed
(e.g. the base CI job) and runs where it is.

Run:  python -m pytest tests/test_realdata.py -v
"""
from __future__ import annotations
import sys, os
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mock_csidata(rate_bpm=15.0, n_time=240, n_sub=64, n_rx=2, fs=20.0, seed=0):
    """A CSIKit CSIData whose amplitude is breathing-modulated at rate_bpm."""
    from CSIKit.csi import CSIData
    rng = np.random.default_rng(seed)
    data = CSIData(); data.chipset = "mock"; data.bandwidth = 20e6
    t = np.arange(n_time) / fs
    # a few subcarriers carry a strong breathing amplitude modulation
    sens = rng.random(n_sub) < 0.25
    base = 1.0 + 0.02 * rng.standard_normal(n_sub)

    class MockFrame:
        def __init__(self, m): self.csi_matrix = m
    for i in range(n_time):
        mod = 1.0 + np.where(sens, 0.06, 0.002) * np.sin(2 * np.pi * (rate_bpm / 60) * t[i])
        amp = base * mod + 0.004 * rng.standard_normal(n_sub)
        phase = 0.3 * rng.standard_normal(n_sub)              # raw uncalibrated-ish phase
        col = (amp * np.exp(1j * phase))[:, None, None] * np.ones((1, n_rx, 1))
        data.push_frame(MockFrame(col.astype(complex)), t[i])
    return data


def test_csidata_to_result_recovers_rate():
    pytest.importorskip("CSIKit")
    from csi_synth import csidata_to_result, estimate_rate
    for rate in (12.0, 15.0, 18.0):
        data = _mock_csidata(rate_bpm=rate, seed=int(rate))
        res = csidata_to_result(data, stream=(0, 0))
        assert res.csi.dtype == complex
        assert res.csi.shape == (240, 64)
        assert abs(res.config.sample_rate - 20.0) < 0.5
        assert res.label["phase_raw_uncalibrated"] is True
        est = estimate_rate(res, band=(0.1, 0.6))
        assert abs(est["bpm"] - rate) < 1.0, f"rate {rate}: got {est['bpm']:.2f}"


def test_load_streams_per_antenna():
    pytest.importorskip("CSIKit")
    from csi_synth import load_streams
    data = _mock_csidata(n_rx=2, seed=5)
    streams = load_streams(data)
    assert len(streams) == 2                           # AX211-style 2 Rx
    assert all(s.csi.shape == (240, 64) for s in streams)


def test_evaluate_and_compare():
    pytest.importorskip("CSIKit")
    from csi_synth import csidata_to_result
    import sim_to_real as S
    real = csidata_to_result(_mock_csidata(rate_bpm=15.0, seed=1))
    m = S.evaluate(real, truth_bpm=15.0)
    assert m["detected"] is True
    assert m["abs_err_bpm"] < 1.0
    # compare() runs two captures through the identical pipeline
    sim = csidata_to_result(_mock_csidata(rate_bpm=15.0, seed=2))
    cmp = S.compare(real, sim, truth_bpm=15.0)
    assert cmp["real"]["detected"] and cmp["sim"]["detected"]


if __name__ == "__main__":
    test_csidata_to_result_recovers_rate()
    test_load_streams_per_antenna()
    test_evaluate_and_compare()
    print("realdata tests: OK")
