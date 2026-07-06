"""
realdata.py — Load REAL captured CSI into the same objects the synthetic pipeline
uses, so estimate_rate / benchmark / PASS / dual-task run unchanged on real data.

Bridge:  capture file  ──CSIKit──▶  CSIData  ──here──▶  CSIResult  ──▶  estimate_rate
                                                                        (same as sim)

CSIKit's get_reader() auto-detects the format, including **FeitCSIBeamformReader**
for Intel AX-series (AX210/AX211) captures produced by FeitCSI/IAX — the tool this
project targets — plus IWL5300, Nexmon, Atheros, ESP32 and CSV. Every reader yields
a CSIData whose frames carry a complex (subcarriers × rx × tx) matrix and a
timestamp; we assemble the canonical (n_time, n_subcarriers) complex array + time
vector and wrap it in a RadioConfig-carrying CSIResult.

CSIKit is an OPTIONAL dependency (it pulls pandas/scikit-learn). Install it only on
the analysis machine:  pip install csikit

Honesty notes:
  * The estimator uses AMPLITUDE, which is robust; RAW Intel/AX phase is corrupted
    (CFO/SFO/PDD) and must be sanitized before any phase-based method — flagged here.
  * Real CSI is non-uniformly sampled; sample_rate is inferred from the timestamps.
  * This is the sim→real bridge; run sim and real through the SAME pipeline and the
    difference is the sim-to-real gap (paper Table I–IV).
"""
from __future__ import annotations
from typing import Optional
import numpy as np

from .generator import RadioConfig, CSIResult

_CSIKIT_HINT = ("CSIKit is required to read real capture files. "
                "Install it on the analysis machine:  pip install csikit")


def _csitools():
    try:
        from CSIKit.util import csitools
        return csitools
    except Exception as e:  # pragma: no cover - env-dependent
        raise ImportError(_CSIKIT_HINT) from e


def csidata_to_result(data, stream=(0, 0), sample_rate: Optional[float] = None,
                      f_center: float = 5.5e9, bandwidth: Optional[float] = None,
                      time_scale: float = 1.0) -> CSIResult:
    """
    Convert a CSIKit CSIData into a csi_synth CSIResult (one Rx/Tx stream).

    stream      : (rx_index, tx_index) to extract — AX211 has 2 Rx; use load_streams()
                  for all of them (MIMO / PASS).
    sample_rate : Hz; if None, inferred from the timestamps (median 1/Δt · time_scale).
    time_scale  : multiply timestamps to convert to SECONDS (e.g. 1e-6 if µs, 1e-9 if ns).
    Returns a CSIResult with complex csi (n_time, n_subcarriers), t, freqs, config, label.
    """
    csitools = _csitools()
    amp, n_frames, n_sub = csitools.get_CSI(data, metric="amplitude",
                                            extract_as_dBm=False, squeeze_output=False)
    phase, _, _ = csitools.get_CSI(data, metric="phase", squeeze_output=False)
    complex_full = amp * np.exp(1j * phase)              # (F, S, Rx, Tx)
    rx, tx = stream
    rx = min(rx, complex_full.shape[2] - 1)
    tx = min(tx, complex_full.shape[3] - 1)
    csi = complex_full[:, :, rx, tx]                     # (F, S)

    ts = np.asarray(getattr(data, "timestamps", []), dtype=float) * time_scale
    if ts.size != csi.shape[0]:
        ts = np.arange(csi.shape[0]) / (sample_rate or 20.0)
    if sample_rate is None:
        dt = np.diff(ts); dt = dt[dt > 0]
        sample_rate = float(1.0 / np.median(dt)) if dt.size else 20.0

    bw = bandwidth or getattr(data, "bandwidth", None) or 20e6
    cfg = RadioConfig(f_center=f_center, bandwidth=float(bw),
                      n_subcarriers=int(csi.shape[1]), sample_rate=float(sample_rate))
    label = {
        "source": "real_capture",
        "chipset": getattr(data, "chipset", None),
        "filename": getattr(data, "filename", None),
        "n_time": int(csi.shape[0]), "stream": [rx, tx],
        "nonuniform_sampling": bool(ts.size and np.std(np.diff(ts)) > 1e-9),
        "phase_raw_uncalibrated": True,   # sanitize before any phase-based method
    }
    return CSIResult(csi=csi, t=ts, freqs=cfg.subcarrier_freqs, label=label, config=cfg)


def load_real_csi(path: str, stream=(0, 0), sample_rate: Optional[float] = None,
                  f_center: float = 5.5e9, time_scale: float = 1.0) -> CSIResult:
    """
    Read a real capture file (auto-detecting FeitCSI/AX211, IWL, Nexmon, ESP32, CSV)
    and return one stream as a CSIResult ready for estimate_rate / the benchmark.
    """
    try:
        from CSIKit.reader import get_reader
    except Exception as e:
        raise ImportError(_CSIKIT_HINT) from e
    reader = get_reader(path)
    data = reader.read_file(path)
    res = csidata_to_result(data, stream=stream, sample_rate=sample_rate,
                            f_center=f_center, time_scale=time_scale)
    res.label["filename"] = path
    return res


def load_streams(path_or_data, sample_rate: Optional[float] = None,
                 f_center: float = 5.5e9, time_scale: float = 1.0) -> list:
    """
    Return a CSIResult per Rx antenna (AX211 → 2), for MIMO / PASS work. Accepts a
    file path or a pre-loaded CSIData.
    """
    if isinstance(path_or_data, str):
        from CSIKit.reader import get_reader
        data = get_reader(path_or_data).read_file(path_or_data)
    else:
        data = path_or_data
    n_rx = data.frames[0].csi_matrix.shape[1] if len(data.frames[0].csi_matrix.shape) >= 2 else 1
    return [csidata_to_result(data, stream=(rx, 0), sample_rate=sample_rate,
                              f_center=f_center, time_scale=time_scale) for rx in range(n_rx)]
