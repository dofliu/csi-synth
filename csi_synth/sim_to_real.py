"""
sim_to_real.py — Run REAL and SYNTHETIC CSI through the SAME pipeline and report
the gap. This is the concrete bridge that fills the paper's Table I–IV: a synthetic
result is only a prediction until the identical pipeline on real AX211 data confirms
(or corrects) it.

Usage:
    # evaluate a real capture (FeitCSI/AX211 auto-detected by CSIKit)
    python sim_to_real.py capture.dat --truth-bpm 15

    # compare a real capture against the twin's matched synthetic export
    python sim_to_real.py capture.dat --sim-csi twin.csv --sim-manifest twin.json --truth-bpm 15

In code:
    from csi_synth.realdata import load_real_csi
    from csi_synth import sim_to_real
    real = load_real_csi("capture.dat")
    print(sim_to_real.evaluate(real, truth_bpm=15))

Metrics per capture: estimated breathing BPM, error vs truth (if given), fused
breathing SNR_eff, detected flag, #frames, sample rate, non-uniform-sampling flag.
Honesty: synthetic numbers are predictions; the REAL column is the measurement.
"""
from __future__ import annotations
import sys, os
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from csi_synth import estimate_rate
from csi_synth import pass_select as PS

BREATH_BAND = (0.15, 0.60)
DETECT_THR = 2.0


def evaluate(result, truth_bpm=None, band=BREATH_BAND, uniform_resample=True):
    """Run the shared estimator on a CSIResult; return a metrics dict."""
    res = result
    if uniform_resample and result.label.get("nonuniform_sampling"):
        try:
            from csi_synth import resample_uniform
            res = resample_uniform(result)
        except Exception:
            res = result
    amp = res.amplitude
    fs = res.config.sample_rate
    subs = PS.select_sensitive(amp, k=min(8, amp.shape[1]), fs=fs, band=band)
    bpm = PS.estimate_rate_subs(amp, subs, fs=fs, band=band)
    snr_eff = PS.fused_snr_eff(amp, subs, fs=fs, band=band)
    # cross-check with the library estimator (amplitude, bandpass+DFT)
    try:
        bpm_est = estimate_rate(res, band=band)["bpm"]
    except Exception:
        bpm_est = None
    out = {
        "source": result.label.get("source", "?"),
        "n_frames": int(amp.shape[0]), "n_sub": int(amp.shape[1]),
        "fs_hz": round(float(fs), 3),
        "bpm": round(float(bpm), 2),
        "bpm_lib": round(float(bpm_est), 2) if bpm_est is not None else None,
        "snr_eff": round(float(snr_eff), 2),
        "detected": bool(snr_eff >= DETECT_THR),
        "nonuniform": bool(result.label.get("nonuniform_sampling", False)),
    }
    if truth_bpm is not None:
        out["truth_bpm"] = truth_bpm
        out["abs_err_bpm"] = round(abs(float(bpm) - truth_bpm), 2)
    return out


def compare(real_result, sim_result, truth_bpm=None, band=BREATH_BAND):
    """Evaluate a real capture and a matched synthetic capture side by side."""
    return {"real": evaluate(real_result, truth_bpm, band),
            "sim": evaluate(sim_result, truth_bpm, band),
            "truth_bpm": truth_bpm}


def _print_row(tag, m):
    err = f"{m.get('abs_err_bpm','—'):>6}" if "abs_err_bpm" in m else "     —"
    print(f"  {tag:<6}{m['bpm']:>7.2f}{err}  {m['snr_eff']:>7.2f}  "
          f"{'yes' if m['detected'] else 'no ':>4}  {m['n_frames']:>6}  {m['fs_hz']:>6.1f}"
          f"  {'non-unif' if m['nonuniform'] else 'uniform'}")


def _print_report(real_m, sim_m=None, truth=None):
    print("=" * 74)
    print(" sim-to-real comparison — same pipeline on real vs synthetic CSI")
    if truth is not None:
        print(f" ground-truth breathing rate: {truth} BPM")
    print("=" * 74)
    print(f"\n  {'':<6}{'BPM':>7}{'|err|':>7}  {'SNR_eff':>7}  {'det':>4}  {'frames':>6}  {'fs':>6}  sampling")
    print("  " + "-" * 66)
    _print_row("REAL", real_m)
    if sim_m is not None:
        _print_row("SIM", sim_m)
        if "abs_err_bpm" in real_m and "abs_err_bpm" in sim_m:
            gap = real_m["abs_err_bpm"] - sim_m["abs_err_bpm"]
            print(f"\n  sim-to-real gap: real error is {gap:+.2f} BPM vs the synthetic prediction.")
    print("\n [the REAL row is the measurement; the SIM row was the prediction]")


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Run real (and optional sim) CSI through the shared pipeline.")
    ap.add_argument("real", help="real capture file (FeitCSI/AX211, IWL, Nexmon, ESP32, CSV)")
    ap.add_argument("--truth-bpm", type=float, default=None)
    ap.add_argument("--stream", type=int, nargs=2, default=[0, 0], metavar=("RX", "TX"))
    ap.add_argument("--time-scale", type=float, default=1.0, help="timestamp→seconds factor (µs=1e-6)")
    ap.add_argument("--sim-csi", default=None, help="twin CSI-window CSV to compare against")
    ap.add_argument("--sim-manifest", default=None, help="twin manifest JSON")
    args = ap.parse_args(argv)

    from csi_synth.realdata import load_real_csi
    real = load_real_csi(args.real, stream=tuple(args.stream), time_scale=args.time_scale)
    real_m = evaluate(real, truth_bpm=args.truth_bpm)
    sim_m = None
    if args.sim_csi:
        from csi_synth import load_twin_csi
        sim = load_twin_csi(args.sim_csi, args.sim_manifest)
        gt = args.truth_bpm
        if gt is None and sim.label.get("ground_truth"):
            gt = (sim.label["ground_truth"] or {}).get("breathing_bpm")
        sim_m = evaluate(sim, truth_bpm=gt)
    _print_report(real_m, sim_m, args.truth_bpm)
    return real_m, sim_m


if __name__ == "__main__":
    main()
