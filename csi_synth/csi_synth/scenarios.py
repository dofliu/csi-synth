"""
scenarios.py — Batch scenario generator.

Produces labelled CSI datasets matching the Chapter 4 data-collection matrix
of the thesis:
    baseline        — empty room (no person)
    normal-supine   — person breathing normally
    posture-{4}     — four sleep postures (different scatter geometry)
    transition      — periodic posture change (turning over)
    apnea-event     — breathing with inserted apnea (breath-hold) segments

Each scenario returns a list of (CSIResult, label) so you can build a
train/val dataset for the pipeline BEFORE real hardware data exists.
"""
from __future__ import annotations
import numpy as np

from .geometry import Room, Node, Person
from .generator import RadioConfig, generate_csi
from .noise import NoiseConfig, apply_noise


# Four sleep postures modelled as different chest positions + scatter offsets.
POSTURES = {
    "supine":      (0.0,  0.0),   # (dx, dy) offset of chest from bed centre
    "left-lateral": (-0.15, 0.05),
    "right-lateral": (0.15, 0.05),
    "prone":       (0.0, -0.10),
}


def _std_room():
    room = Room(width=5.0, depth=4.0)
    tx = Node(0.6, 2.0)
    rx = Node(4.4, 2.0)
    bed_centre = (2.5, 2.0)
    return room, tx, rx, bed_centre


def make_scenario(
    kind: str,
    duration: float = 30.0,
    config: RadioConfig | None = None,
    noise: NoiseConfig | None = None,
    seed: int | None = None,
) -> "CSIResult":
    """Generate a single labelled scenario. See module docstring for kinds."""
    from .generator import CSIResult  # local import for type
    room, tx, rx, (bx, by) = _std_room()
    cfg = config or RadioConfig()

    if kind == "baseline":
        person = Person(bx, by, breathing=None, heartbeat=None, present=False)
        res = generate_csi(room, tx, rx, person, duration, cfg, {"scenario": "baseline"})

    elif kind == "normal-supine":
        person = Person(bx, by, breathing={"rate_bpm": 15.0, "amplitude_mm": 5.0})
        res = generate_csi(room, tx, rx, person, duration, cfg, {"scenario": "normal-supine", "br_bpm": 15.0})

    elif kind.startswith("posture-"):
        p = kind.split("-", 1)[1]
        dx, dy = POSTURES.get(p, (0.0, 0.0))
        person = Person(bx + dx, by + dy, breathing={"rate_bpm": 14.0, "amplitude_mm": 5.0})
        res = generate_csi(room, tx, rx, person, duration, cfg,
                           {"scenario": kind, "posture": p, "br_bpm": 14.0})

    elif kind == "transition":
        res = _make_transition(room, tx, rx, (bx, by), duration, cfg)

    elif kind == "apnea-event":
        res = _make_apnea(room, tx, rx, (bx, by), duration, cfg)

    else:
        raise ValueError(f"unknown scenario kind: {kind}")

    if noise is not None:
        if seed is not None and noise.seed is None:
            noise.seed = seed
        res = apply_noise(res, noise)
    return res


def _make_transition(room, tx, rx, bed, duration, cfg):
    """Person changes posture every ~duration/3 seconds (turning over)."""
    from .generator import generate_csi
    bx, by = bed
    seg = duration / 3.0
    postures = ["supine", "left-lateral", "right-lateral"]
    parts = []
    labels_time = []
    for i, p in enumerate(postures):
        dx, dy = POSTURES[p]
        person = Person(bx + dx, by + dy, breathing={"rate_bpm": 15.0, "amplitude_mm": 5.0})
        r = generate_csi(room, tx, rx, person, seg, cfg)
        parts.append(r.csi)
        labels_time.append({"start": i * seg, "end": (i + 1) * seg, "posture": p})
    csi = np.concatenate(parts, axis=0)
    t = np.arange(csi.shape[0]) / cfg.sample_rate
    from .generator import CSIResult
    return CSIResult(csi=csi, t=t, freqs=cfg.subcarrier_freqs,
                     label={"scenario": "transition", "segments": labels_time},
                     config=cfg)


def _make_apnea(room, tx, rx, bed, duration, cfg):
    """
    Normal breathing with inserted apnea (breath-hold) segments.
    During apnea, breathing amplitude -> 0 (chest stops moving).
    Produces a per-time apnea mask as ground truth.
    """
    from .generator import CSIResult
    bx, by = bed
    n_time = int(round(duration * cfg.sample_rate))
    t = np.arange(n_time) / cfg.sample_rate

    # Apnea events: 10 s hold, every 30 s, starting at 15 s
    apnea_mask = np.zeros(n_time, dtype=bool)
    for start in np.arange(15.0, duration, 30.0):
        idx = (t >= start) & (t < start + 10.0)
        apnea_mask |= idx

    # Build a time-varying breathing amplitude
    person = Person(bx, by, breathing={"rate_bpm": 12.0, "amplitude_mm": 5.0})

    # Generate per-sample by scaling chest displacement with the mask.
    # We recompute the scatter modulation directly for control.
    from .geometry import path_lengths
    from .generator import C
    freqs = cfg.subcarrier_freqs
    disp_full = person.chest_displacement(t)
    disp_full[apnea_mask] = 0.0  # breath held -> no chest motion

    csi = np.zeros((n_time, freqs.size), dtype=complex)
    k_phase = -1j * 2 * np.pi / C
    for i in range(n_time):
        paths = path_lengths(tx, rx, person, room, extra_scatter=2.0 * disp_full[i])
        h = np.zeros(freqs.size, dtype=complex)
        for length, amp, _ in paths:
            h += amp * np.exp(k_phase * freqs * length)
        csi[i] = h

    return CSIResult(csi=csi, t=t, freqs=freqs,
                     label={"scenario": "apnea-event", "br_bpm": 12.0,
                            "apnea_mask": apnea_mask.tolist(),
                            "n_events": int(np.sum(np.diff(apnea_mask.astype(int)) == 1))},
                     config=cfg)


def build_dataset(
    duration: float = 30.0,
    config: RadioConfig | None = None,
    noise: NoiseConfig | None = None,
) -> list:
    """Generate one instance of every scenario. Returns list of CSIResult."""
    kinds = [
        "baseline", "normal-supine",
        "posture-supine", "posture-left-lateral",
        "posture-right-lateral", "posture-prone",
        "transition", "apnea-event",
    ]
    out = []
    for i, k in enumerate(kinds):
        out.append(make_scenario(k, duration, config, noise, seed=i))
    return out
