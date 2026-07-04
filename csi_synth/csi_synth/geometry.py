"""
geometry.py — Room geometry, node placement, and multipath path-length computation.

All distances are in metres. The synthetic CSI generator is built on an
image-source multipath model: the received signal is the coherent sum of a
direct Tx->Rx path, a person-scattered path, and first-order wall reflections.

This module is pure geometry — no signal/CSI logic lives here.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np


@dataclass
class Room:
    """A rectangular room. Origin at one corner; +x width, +y depth."""
    width: float = 5.0    # metres (x)
    depth: float = 4.0    # metres (y)

    def clamp(self, x: float, y: float, margin: float = 0.1) -> tuple[float, float]:
        """Keep a point inside the room walls."""
        return (
            float(np.clip(x, margin, self.width - margin)),
            float(np.clip(y, margin, self.depth - margin)),
        )


@dataclass
class Node:
    """A Tx or Rx antenna position."""
    x: float
    y: float

    @property
    def xy(self) -> np.ndarray:
        return np.array([self.x, self.y], dtype=float)


@dataclass
class Person:
    """
    A person in the room, modelled as a point scatterer whose thorax
    surface oscillates with breathing (and optionally heartbeat).

    x, y      : chest centre position (metres)
    breathing : dict with keys {rate_bpm, amplitude_mm} or None
    heartbeat : dict with keys {rate_bpm, amplitude_mm} or None
    present   : if False, the person contributes no scattering (empty room)
    """
    x: float
    y: float
    breathing: dict | None = field(default_factory=lambda: {"rate_bpm": 15.0, "amplitude_mm": 5.0})
    heartbeat: dict | None = None
    present: bool = True

    @property
    def xy(self) -> np.ndarray:
        return np.array([self.x, self.y], dtype=float)

    def chest_displacement(self, t: np.ndarray) -> np.ndarray:
        """
        Radial chest-surface displacement in METRES at times t (seconds).
        Sum of breathing and (optional) heartbeat sinusoids.
        """
        d = np.zeros_like(t, dtype=float)
        if self.breathing is not None:
            a = self.breathing["amplitude_mm"] * 1e-3
            f = self.breathing["rate_bpm"] / 60.0
            d = d + a * np.sin(2 * np.pi * f * t)
        if self.heartbeat is not None:
            a = self.heartbeat["amplitude_mm"] * 1e-3
            f = self.heartbeat["rate_bpm"] / 60.0
            d = d + a * np.sin(2 * np.pi * f * t)
        return d


def _dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.hypot(*(a - b)))


def image_sources(tx: np.ndarray, room: Room) -> list[np.ndarray]:
    """First-order image sources of the Tx across the 4 walls."""
    x, y = tx
    return [
        np.array([-x, y]),                    # left wall  (x=0)
        np.array([2 * room.width - x, y]),    # right wall (x=W)
        np.array([x, -y]),                    # front wall (y=0)
        np.array([x, 2 * room.depth - y]),    # back wall  (y=D)
    ]


def path_lengths(
    tx: Node, rx: Node, person: Person, room: Room,
    extra_scatter: float = 0.0,
):
    """
    Compute the set of propagation path lengths (metres) and their base
    (geometry-only) amplitudes for one instant.

    extra_scatter: additional path length added to the person-scattered path,
                   used to inject breathing/heartbeat chest displacement.

    Returns a list of (length, amplitude, kind) tuples. `kind` is one of
    'direct', 'scatter', 'reflect' — useful for debugging / visualisation.
    """
    paths = []

    # 1) Direct path (line-of-sight)
    d_direct = _dist(tx.xy, rx.xy)
    paths.append((d_direct, 1.0 / (d_direct + 1e-3), "direct"))

    # 2) Person-scattered path Tx -> person -> Rx
    if person.present:
        d_tp = _dist(tx.xy, person.xy)
        d_pr = _dist(person.xy, rx.xy)
        d_scatter = d_tp + d_pr + extra_scatter
        # Scatter amplitude falls off with the two-hop distance and a
        # scattering cross-section factor (0.5 empirical, as in the demo).
        a_scatter = 0.5 / (d_scatter + 1e-3)
        paths.append((d_scatter, a_scatter, "scatter"))

    # 3) First-order wall reflections
    refl_coeff = [0.36, 0.36, 0.30, 0.30]  # per-wall reflection amplitude
    for img, rc in zip(image_sources(tx.xy, room), refl_coeff):
        d_w = _dist(img, rx.xy)
        paths.append((d_w, rc / (d_w + 1e-3), "reflect"))

    return paths
