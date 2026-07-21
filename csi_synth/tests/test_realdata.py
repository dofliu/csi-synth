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


# ───────────────────────── amplitude-only 'Timestamp,Sub_N' CSV path ─────────────────────────
# No CSIKit needed here — this is the schema this project's own capture/decode
# scripts actually produce (confirmed against real ESP32 captures), and CSIKit's
# own get_reader() cannot parse it (silently mis-detects it as Intel binary).

def _write_amplitude_csv(path, rate_bpm=15.0, n_time=200, n_sub=52, fs=6.1, seed=0,
                         null_band=range(23, 32), hh_mm_ss=True):
    """Write a CSV in the real 'Timestamp,Sub_0..Sub_{N-1}' schema, with a null/
    guard band of exact zeros (as seen on real ESP32-CSI-tool captures) and a
    breathing-band amplitude modulation on the non-null subcarriers."""
    import csv as _csv
    from datetime import datetime, timedelta
    rng = np.random.default_rng(seed)
    t = np.arange(n_time) / fs
    base = 20.0 + 5.0 * rng.standard_normal(n_sub)
    with open(path, "w", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(["Timestamp"] + [f"Sub_{k}" for k in range(n_sub)])
        start = datetime(2026, 1, 1, 2, 0, 0)
        for i in range(n_time):
            mod = 1.0 + 0.08 * np.sin(2 * np.pi * (rate_bpm / 60) * t[i])
            row_amp = np.abs(base * mod + 0.3 * rng.standard_normal(n_sub))
            for k in null_band:
                row_amp[k] = 0.0
            ts = (start + timedelta(seconds=float(t[i]))).strftime("%H:%M:%S.%f")[:-3] \
                if hh_mm_ss else f"{t[i]:.3f}"
            w.writerow([ts] + [f"{v:.6f}" for v in row_amp])


def test_looks_like_amplitude_csv_detection(tmp_path):
    from csi_synth.realdata import _looks_like_amplitude_csv
    p = tmp_path / "real.csv"
    _write_amplitude_csv(str(p))
    assert _looks_like_amplitude_csv(str(p)) is True
    # a generic (non-matching) CSV should not be detected as this schema
    other = tmp_path / "other.csv"
    other.write_text("time,a,b\n0,1,2\n")
    assert _looks_like_amplitude_csv(str(other)) is False


def test_load_amplitude_csv_recovers_rate_and_null_band(tmp_path):
    from csi_synth import load_amplitude_csv, estimate_rate
    p = tmp_path / "clean_room.csv"
    _write_amplitude_csv(str(p), rate_bpm=15.0, fs=6.1, seed=3)
    res = load_amplitude_csv(str(p))
    assert res.csi.shape == (200, 52)
    assert res.label["phase_available"] is False
    # sample rate must be MEASURED from timestamps, not assumed — this is the
    # exact bug class that would silently corrupt every frequency estimate
    assert 5.5 < res.config.sample_rate < 6.7
    # the null/guard band is exact zeros, same as the real captures
    amp = res.amplitude
    assert np.all(amp[:, 23:32] == 0.0)
    assert np.mean(amp[:, :20]) > 1.0
    est = estimate_rate(res, band=(0.1, 0.6))
    assert abs(est["bpm"] - 15.0) < 2.0


def test_load_real_csi_auto_detects_amplitude_csv(tmp_path):
    """load_real_csi() must route to the CSV path WITHOUT touching CSIKit at all —
    this is what silently failed against the real files before this fix."""
    from csi_synth import load_real_csi
    p = tmp_path / "capture.csv"
    _write_amplitude_csv(str(p), rate_bpm=13.0, fs=6.1, seed=4)
    res = load_real_csi(str(p))
    assert res.label["source"] == "real_capture_amplitude_csv"
    assert res.csi.shape[1] == 52


def test_timestamp_seconds_parses_hhmmss_and_handles_midnight_rollover():
    from csi_synth.realdata import _parse_timestamp_seconds
    vals = ["23:59:58.000", "23:59:59.000", "00:00:00.500", "00:00:01.500"]
    t = _parse_timestamp_seconds(vals)
    assert np.allclose(t, [0.0, 1.0, 2.5, 3.5])


if __name__ == "__main__":
    test_csidata_to_result_recovers_rate()
    test_load_streams_per_antenna()
    test_evaluate_and_compare()
    print("realdata tests: OK")
