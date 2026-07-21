"""
realdata.py — Load REAL captured CSI into the same objects the synthetic pipeline
uses, so estimate_rate / benchmark / PASS / dual-task run unchanged on real data.

Two ingestion paths, auto-selected by load_real_csi():

  1. capture file ──CSIKit──▶ CSIData ──here──▶ CSIResult ──▶ estimate_rate (same as sim)
     CSIKit's get_reader() auto-detects binary formats, including
     **FeitCSIBeamformReader** for Intel AX-series (AX210/AX211) captures produced
     by FeitCSI/IAX — the tool this project targets — plus IWL5300, Nexmon, Atheros.
     CSIKit is an OPTIONAL dependency (pulls pandas/scikit-learn):
         pip install csikit

  2. amplitude-only 'Timestamp,Sub_0..Sub_{N-1}' CSV ──here──▶ CSIResult
     This is the schema this project's own capture/decode scripts have actually
     been producing (e.g. ESP32-CSI-tool exports): a header row, then one row per
     packet with a wall-clock timestamp and per-subcarrier AMPLITUDE (no phase).
     CSIKit's get_reader() does NOT recognize this schema — it silently
     mis-identifies it as raw Intel binary and returns 0 frames after printing a
     wall of "Invalid code" noise (confirmed against real files; see
     EXPERIMENT_PROTOCOL.md pitfalls). load_real_csi() detects this schema from the
     header and routes to load_amplitude_csv() directly, needing neither CSIKit nor
     pandas.

Honesty notes:
  * The estimator uses AMPLITUDE, which is robust; RAW Intel/AX phase is corrupted
    (CFO/SFO/PDD) and must be sanitized before any phase-based method — flagged here.
    The amplitude-CSV path has no phase at all (csi = amplitude + 0j); estimate_rate/
    pass_select operate on np.abs(csi), which is unaffected.
  * Real CSI is non-uniformly sampled; sample_rate is inferred from the timestamps —
    NEVER assume the 20 Hz used elsewhere as a synthetic default. A real capture at
    ~6 Hz (not 20) has been observed in practice — likely a passive/beacon-rate
    monitor-mode capture rather than an actively-solicited high-rate one; worth
    checking the capture tool's configuration if a higher rate is expected.
  * This is the sim→real bridge; run sim and real through the SAME pipeline and the
    difference is the sim-to-real gap (paper Table I–IV).
"""
from __future__ import annotations
from typing import Optional
import csv as _csv
import re as _re
from datetime import datetime as _datetime
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


def _looks_like_amplitude_csv(path: str) -> bool:
    """
    Detect the 'Timestamp,Sub_0,Sub_1,...' amplitude-only CSV schema (see module
    docstring). CSIKit's get_reader() does not recognize it and mis-parses it as
    Intel binary, so this must be checked BEFORE falling through to CSIKit.
    """
    if not path.lower().endswith(".csv"):
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            header = fh.readline().strip()
    except OSError:
        return False
    cols = header.split(",")
    return (len(cols) >= 2 and cols[0].strip().lower() == "timestamp"
            and cols[1].strip().startswith("Sub_"))


def _parse_timestamp_seconds(values: list) -> np.ndarray:
    """
    Parse a column of timestamps into seconds-from-start floats (float64 array,
    t[0] == 0). Handles bare 'HH:MM:SS[.ffffff]' time-of-day (no date — common in
    quick capture-script exports) and unwraps a midnight rollover; falls back to
    plain float seconds or ISO-8601 datetimes.
    """
    first = str(values[0]).strip()
    if _re.match(r"^\d{1,2}:\d{2}:\d{2}", first):
        fmt = "%H:%M:%S.%f" if "." in first else "%H:%M:%S"
        t = np.empty(len(values), dtype=float)
        offset = 0.0
        prev_secs = None
        for i, v in enumerate(values):
            dt = _datetime.strptime(str(v).strip(), fmt)
            secs = dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1e6
            if prev_secs is not None and secs < prev_secs:
                offset += 86400.0  # crossed midnight
            t[i] = secs + offset
            prev_secs = secs
        t -= t[0]
        return t
    try:
        t = np.array([float(v) for v in values], dtype=float)
    except ValueError:
        dts = [_datetime.fromisoformat(str(v).strip()) for v in values]
        t = np.array([(d - dts[0]).total_seconds() for d in dts], dtype=float)
        return t
    return t - t[0]


def load_amplitude_csv(path: str, f_center: float = 2.437e9, bandwidth: float = 20e6,
                       sample_rate: Optional[float] = None) -> CSIResult:
    """
    Load the 'Timestamp,Sub_0..Sub_{N-1}' amplitude-only CSV schema (no CSIKit or
    pandas required). No phase is available: csi is set to amplitude + 0j, which
    estimate_rate/pass_select consume unchanged via np.abs(csi).

    sample_rate: Hz; if None, inferred from the median timestamp spacing. Do NOT
    assume any nominal rate — measure it (see module docstring: ~6 Hz observed on
    a real low-duty-cycle capture, well below the 20 Hz used as a synthetic default
    elsewhere in this package).
    """
    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as fh:
        rows = list(_csv.reader(fh))
    if len(rows) < 2:
        raise ValueError(f"no data rows in {path}")
    header, data_rows = rows[0], rows[1:]
    ts_raw = [r[0] for r in data_rows]
    amp = np.array([[float(x) for x in r[1:]] for r in data_rows], dtype=float)
    t = _parse_timestamp_seconds(ts_raw)

    if sample_rate is None:
        dt = np.diff(t)
        dt = dt[dt > 0]
        sample_rate = float(1.0 / np.median(dt)) if dt.size else 20.0

    cfg = RadioConfig(f_center=f_center, bandwidth=bandwidth,
                      n_subcarriers=int(amp.shape[1]), sample_rate=float(sample_rate))
    label = {
        "source": "real_capture_amplitude_csv", "filename": path,
        "n_time": int(amp.shape[0]), "n_subcarriers": int(amp.shape[1]),
        "phase_available": False,
        "nonuniform_sampling": bool(t.size > 1 and np.std(np.diff(t)) > 1e-3),
    }
    return CSIResult(csi=amp.astype(complex), t=t, freqs=cfg.subcarrier_freqs,
                     label=label, config=cfg)


def load_real_csi(path: str, stream=(0, 0), sample_rate: Optional[float] = None,
                  f_center: float = 5.5e9, time_scale: float = 1.0) -> CSIResult:
    """
    Read a real capture file and return one stream as a CSIResult ready for
    estimate_rate / the benchmark. Auto-detects the amplitude-only
    'Timestamp,Sub_N' CSV schema (routed to load_amplitude_csv, no CSIKit needed);
    otherwise falls through to CSIKit's get_reader() (FeitCSI/AX211, IWL, Nexmon,
    ESP32 binary, generic CSV).
    """
    if _looks_like_amplitude_csv(path):
        return load_amplitude_csv(path, sample_rate=sample_rate)
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
