"""
generator.py — Physically-grounded synthetic CSI generator.

Builds a complex channel frequency response H(f, t) by coherently summing
multipath components, then samples it on the OFDM subcarrier grid over time.

Physics:
    For each subcarrier at frequency f_k = f_c + (k - N/2) * (BW / N),
    each path of length d contributes:
        a * exp(-j * 2*pi*f_k * d / c)
    The person-scattered path length is modulated by the chest displacement,
    which is what makes breathing/heartbeat observable in CSI phase/amplitude.

The output is CLEAN (noise-free). Noise/hardware impairments are applied
separately in noise.py so the physical core stays verifiable.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

from .geometry import Room, Node, Person, path_lengths

C = 299_792_458.0  # speed of light, m/s


@dataclass
class RadioConfig:
    """OFDM / WiFi radio parameters."""
    f_center: float = 2.437e9   # Hz (2.4 GHz, ch 6). Use 5.5e9 for 5 GHz.
    bandwidth: float = 20e6     # Hz
    n_subcarriers: int = 56     # 56 (20MHz HT) ... up to 256 (160MHz ax)
    sample_rate: float = 100.0  # CSI packets per second (Hz)

    @property
    def subcarrier_freqs(self) -> np.ndarray:
        k = np.arange(self.n_subcarriers)
        return self.f_center + (k - self.n_subcarriers / 2 + 0.5) * (
            self.bandwidth / self.n_subcarriers
        )


@dataclass
class CSIResult:
    """Container for a generated CSI time series."""
    csi: np.ndarray          # complex, shape (n_time, n_subcarriers)
    t: np.ndarray            # seconds, shape (n_time,)
    freqs: np.ndarray        # Hz, shape (n_subcarriers,)
    label: dict              # ground-truth metadata
    config: RadioConfig

    @property
    def amplitude(self) -> np.ndarray:
        return np.abs(self.csi)

    @property
    def phase(self) -> np.ndarray:
        return np.angle(self.csi)


def generate_csi(
    room: Room,
    tx: Node,
    rx: Node,
    person: Person,
    duration: float = 30.0,
    config: RadioConfig | None = None,
    label: dict | None = None,
) -> CSIResult:
    """
    Generate a clean (noise-free) CSI time series.

    duration : seconds
    Returns a CSIResult with complex CSI of shape (n_time, n_subcarriers).
    """
    cfg = config or RadioConfig()
    freqs = cfg.subcarrier_freqs
    n_time = int(round(duration * cfg.sample_rate))
    t = np.arange(n_time) / cfg.sample_rate

    # Chest displacement over time (metres). This modulates the scatter path.
    disp = person.chest_displacement(t) if person.present else np.zeros(n_time)

    # Pre-allocate complex CSI
    csi = np.zeros((n_time, freqs.size), dtype=complex)

    # Precompute constant -j*2*pi/c
    k_phase = -1j * 2 * np.pi / C

    for i in range(n_time):
        # The chest surface moves toward the incident wave, adding ~2*disp to
        # the round-trip scatter path (factor 2 = go and return geometry).
        extra = 2.0 * disp[i]
        paths = path_lengths(tx, rx, person, room, extra_scatter=extra)

        # Sum contributions across all paths for every subcarrier at once.
        h = np.zeros(freqs.size, dtype=complex)
        for length, amp, _kind in paths:
            h += amp * np.exp(k_phase * freqs * length)
        csi[i] = h

    lbl = {
        "room": {"width": room.width, "depth": room.depth},
        "tx": [tx.x, tx.y],
        "rx": [rx.x, rx.y],
        "person": {
            "present": person.present,
            "xy": [person.x, person.y],
            "breathing": person.breathing,
            "heartbeat": person.heartbeat,
        },
        "duration": duration,
    }
    if label:
        lbl.update(label)

    return CSIResult(csi=csi, t=t, freqs=freqs, label=lbl, config=cfg)
