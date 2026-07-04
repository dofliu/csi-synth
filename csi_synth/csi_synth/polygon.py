"""
polygon.py — Polygon rooms with physically-valid multipath (Stage-3).

WHY THIS EXISTS
The rectangular generator uses the image-source method, which is only valid
for convex rooms. For a concave room (e.g. an L-shape) the naive image-source
method invents reflection paths that pass THROUGH walls that do not exist,
producing physically wrong CSI. This module fixes that and adds the mechanism
a concave room introduces but image-source omits: edge diffraction at reentrant
(reflex) corners.

WHAT IS MODELLED (ray-based, physically grounded)
  * Direct path Tx->Rx, with an occlusion test (in an L-room the two arms may
    have no line of sight).
  * First-order specular reflections off each wall segment, VALIDATED: the
    reflection point must lie on the finite wall segment, and both the incident
    and reflected rays must be unobstructed by any other wall. This validation
    is exactly what removes the image-source method's spurious paths.
  * Edge diffraction at each reflex corner via a simplified Uniform Theory of
    Diffraction (UTD) coefficient: the corner acts as a secondary line source,
    Tx->corner->Rx, with a magnitude that falls off with the diffraction angle
    and with 1/sqrt spreading. Both legs are occlusion-tested.

HONEST SCOPE
This is a first-order ray model: single reflections and single diffractions,
no reflection-diffraction combinations, no transmission through walls, no
frequency-dependent material response. It is physically correct in KIND (it
respects visibility and adds diffraction) and is far more faithful for concave
rooms than image-source, but it is still a model; absolute values must be
validated on real data. The simplified UTD coefficient captures the qualitative
behaviour of diffraction, not its exact amplitude.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

EPS = 1e-9


# ───────────────────────── geometry primitives ─────────────────────────
def _seg_intersect(p1, p2, p3, p4, exclude_shared=True):
    """True if segment p1p2 properly intersects segment p3p4."""
    p1, p2, p3, p4 = map(np.asarray, (p1, p2, p3, p4))
    d1 = p2 - p1; d2 = p4 - p3
    denom = d1[0]*d2[1] - d1[1]*d2[0]
    if abs(denom) < EPS:
        return False  # parallel / collinear -> treat as non-blocking
    t = ((p3[0]-p1[0])*d2[1] - (p3[1]-p1[1])*d2[0]) / denom
    u = ((p3[0]-p1[0])*d1[1] - (p3[1]-p1[1])*d1[0]) / denom
    lo, hi = (EPS, 1-EPS) if exclude_shared else (-EPS, 1+EPS)
    return (lo < t < hi) and (lo < u < hi)


def _mirror_point(p, a, b):
    """Mirror point p across the infinite line through a, b."""
    p, a, b = map(np.asarray, (p, a, b), (float, float, float))
    ab = b - a
    t = np.dot(p - a, ab) / (np.dot(ab, ab) + EPS)
    foot = a + t*ab
    return 2*foot - p


def _point_on_segment(p, a, b):
    """Parametric position of p along segment a->b (assumes p on the line)."""
    a, b = np.asarray(a), np.asarray(b)
    ab = b - a
    return np.dot(np.asarray(p) - a, ab) / (np.dot(ab, ab) + EPS)


# ───────────────────────── polygon room ─────────────────────────
@dataclass
class PolygonRoom:
    """
    A room defined by an ordered list of (x, y) vertices (counter-clockwise).
    Walls are the segments between consecutive vertices (closed loop).
    """
    vertices: list                      # list of (x, y)
    reflect_coeff: float = 0.6          # nominal wall reflection magnitude
    interior_walls: list = field(default_factory=list)  # list of ((x1,y1),(x2,y2)) partitions

    def __post_init__(self):
        self.V = [np.asarray(v, dtype=float) for v in self.vertices]
        self.n = len(self.V)
        # ensure counter-clockwise (positive signed area)
        if self._signed_area() < 0:
            self.V = self.V[::-1]
        self.walls = [(self.V[i], self.V[(i+1) % self.n]) for i in range(self.n)]
        # interior partition segments (independent free-standing walls)
        self.interior = [(np.asarray(a, float), np.asarray(b, float)) for (a, b) in self.interior_walls]
        # combined list used for occlusion + reflection (outer walls THEN interior)
        self.segments = self.walls + self.interior

    def _signed_area(self):
        s = 0.0
        for i in range(len(self.V)):
            x1, y1 = self.V[i]; x2, y2 = self.V[(i+1) % len(self.V)]
            s += x1*y2 - x2*y1
        return 0.5*s

    def bbox(self):
        xs = [v[0] for v in self.V]; ys = [v[1] for v in self.V]
        return min(xs), min(ys), max(xs), max(ys)

    def is_inside(self, p):
        """Ray-casting point-in-polygon test."""
        x, y = p; inside = False
        for (a, b) in self.walls:
            (x1, y1), (x2, y2) = a, b
            if (y1 > y) != (y2 > y):
                xint = x1 + (y - y1)/(y2 - y1 + EPS)*(x2 - x1)
                if x < xint:
                    inside = not inside
        return inside

    def blocked(self, p1, p2, ignore_walls=()):
        """True if segment p1->p2 is intersected by any wall or partition (occlusion)."""
        for i, (a, b) in enumerate(self.segments):
            if i in ignore_walls:
                continue
            if _seg_intersect(p1, p2, a, b):
                return True
        return False

    def _on_outer_wall(self, p, tol=1e-6):
        """True if point p lies on (touches) any outer wall segment."""
        for (a, b) in self.walls:
            ab = b - a; L2 = np.dot(ab, ab)
            if L2 < EPS:
                continue
            t = np.clip(np.dot(np.asarray(p) - a, ab) / L2, 0, 1)
            foot = a + t*ab
            if np.hypot(*(np.asarray(p) - foot)) < tol:
                return True
        return False

    def diffracting_edges(self):
        """
        Points that diffract: reflex (reentrant) outer corners PLUS the FREE
        endpoints of each interior partition. An endpoint embedded in an outer
        wall is not a free edge and does not diffract.
        """
        pts = [C for _, C in self.reflex_corners()]
        for (a, b) in self.interior:
            for ep in (a, b):
                if not self._on_outer_wall(ep):
                    pts.append(ep)
        return pts

    def reflex_corners(self):
        """
        Return indices+points of reflex (reentrant, interior angle > 180 deg)
        vertices — these are the ones that diffract. For a CCW polygon a vertex
        is reflex if the cross product of incoming and outgoing edges is < 0.
        """
        out = []
        for i in range(self.n):
            prev = self.V[(i-1) % self.n]; cur = self.V[i]; nxt = self.V[(i+1) % self.n]
            e1 = cur - prev; e2 = nxt - cur
            cross = e1[0]*e2[1] - e1[1]*e2[0]
            if cross < -EPS:                 # reflex for CCW polygon
                out.append((i, cur))
        return out

    # ---- path enumeration ----
    def direct_path(self, tx, rx):
        """(length, weight) for the direct path if unobstructed, else None."""
        if self.blocked(tx, rx):
            return None
        d = float(np.hypot(rx[0]-tx[0], rx[1]-tx[1]))
        return (d, 1.0/(d + 0.1))

    def reflection_paths(self, tx, rx):
        """Validated first-order specular reflections off outer walls AND interior
        partitions (partitions reflect from both sides). Returns list of (length, weight)."""
        tx = np.asarray(tx, float); rx = np.asarray(rx, float)
        paths = []
        for wi, (a, b) in enumerate(self.segments):
            img = _mirror_point(tx, a, b)                 # image of Tx across the segment
            d1 = rx - img; d2 = b - a
            denom = d1[0]*d2[1] - d1[1]*d2[0]
            if abs(denom) < EPS:
                continue
            t = ((a[0]-img[0])*d2[1] - (a[1]-img[1])*d2[0]) / denom   # along img->rx
            u = ((a[0]-img[0])*d1[1] - (a[1]-img[1])*d1[0]) / denom   # along a->b
            if not (0.0 <= u <= 1.0) or t <= 0:
                continue                                   # reflection point off the segment
            P = img + t*d1
            if self.blocked(tx, P, ignore_walls=(wi,)) or self.blocked(P, rx, ignore_walls=(wi,)):
                continue
            length = float(np.hypot(P[0]-tx[0], P[1]-tx[1]) + np.hypot(rx[0]-P[0], rx[1]-P[1]))
            paths.append((length, self.reflect_coeff/(length + 0.1)))
        return paths

    def diffraction_paths(self, tx, rx, coeff=0.28):
        """
        Simplified UTD edge diffraction at every diffracting edge: reflex outer
        corners and free interior-partition endpoints. Each edge is a secondary
        source Tx->edge->Rx; magnitude falls off with the deviation from
        straight-through and with 1/sqrt spreading. Both legs are occlusion-tested.
        """
        tx = np.asarray(tx, float); rx = np.asarray(rx, float)
        paths = []
        for C in self.diffracting_edges():
            if self.blocked(tx, C) or self.blocked(C, rx):
                continue
            d_in = np.hypot(C[0]-tx[0], C[1]-tx[1])
            d_out = np.hypot(rx[0]-C[0], rx[1]-C[1])
            vin = (C - tx)/(d_in + EPS); vout = (rx - C)/(d_out + EPS)
            cos_dev = np.clip(np.dot(vin, vout), -1, 1)
            dev = np.arccos(cos_dev)                       # 0 = straight through
            ang = np.exp(-(dev/1.2)**2)                    # angular taper
            spread = 1.0/np.sqrt((d_in*d_out/(d_in+d_out)) + 0.1)
            w = coeff*ang*spread
            length = float(d_in + d_out)
            if w > 1e-4:
                paths.append((length, w))
        return paths

    def all_paths(self, tx, rx):
        """Direct + validated reflections + reflex-corner diffractions."""
        paths = []
        dp = self.direct_path(tx, rx)
        if dp:
            paths.append(dp)
        paths += self.reflection_paths(tx, rx)
        paths += self.diffraction_paths(tx, rx)
        return paths


# ───────────────────────── common shapes ─────────────────────────
def rect_room(w=5.0, h=4.0):
    return PolygonRoom([(0, 0), (w, 0), (w, h), (0, h)])


def l_room(w=6.0, h=5.0, cut_w=2.5, cut_h=2.0):
    """
    L-shaped room: a w x h rectangle with a rectangular notch of size
    cut_w x cut_h removed from the top-right corner. The reentrant vertex
    is the diffracting inner corner.
    """
    return PolygonRoom([
        (0, 0), (w, 0), (w, h-cut_h),
        (w-cut_w, h-cut_h),            # <-- reflex (inner) corner
        (w-cut_w, h), (0, h),
    ])


def partition_room(w=6.0, h=5.0, part_x=3.0, gap=1.2):
    """
    Rectangular room with a free-standing interior partition (an inner wall) at
    x = part_x, running from the bottom wall up to leave a doorway `gap` below
    the top wall. The partition strongly occludes the two sides; the wave must
    reflect or diffract around the partition's free top endpoint (and through
    the doorway). The most severe common home layout.
    """
    return PolygonRoom(
        [(0, 0), (w, 0), (w, h), (0, h)],
        interior_walls=[((part_x, 0.0), (part_x, h-gap))],   # free top endpoint at (part_x, h-gap)
    )


def slanted_room(w=6.0, h=5.0, slant=2.0):
    """
    Convex trapezoidal room with one slanted wall (e.g. an attic/loft ceiling in
    plan, or a non-rectangular corner). No occlusion (still convex), but the
    reflection geometry is asymmetric, shifting the sensitive-subcarrier set.
    """
    return PolygonRoom([
        (0, 0), (w, 0), (w, h-slant), (w-slant, h), (0, h),
    ])


# ───────────────────────── CSI generation for polygon rooms ─────────────────────────
def generate_polygon_csi(room, tx, rx, body_xy, resp_disp, freqs, present=True):
    """
    One-frame complex CSI for a polygon room.
      room      : PolygonRoom
      tx, rx    : (x,y)
      body_xy   : (x,y) person position
      resp_disp : scalar radial displacement (m) this frame (breathing)
      freqs     : subcarrier frequencies (Hz)
    Static channel = direct + validated reflections + reflex-corner diffraction.
    Person channel = Tx->person->Rx if BOTH legs are unobstructed (else the
    person is in a shadow zone and contributes only via a weak diffracted
    scatter, if the corner is visible to both).
    Returns complex ndarray (len(freqs),).
    """
    C = 299_792_458.0
    tx = np.asarray(tx, float); rx = np.asarray(rx, float); body = np.asarray(body_xy, float)
    k2pi = 2*np.pi
    h = np.zeros(freqs.size, dtype=complex)
    # static multipath
    for length, w in room.all_paths(tx, rx):
        h += w*np.exp(-1j*k2pi*freqs*length/C)
    # person scattering with occlusion
    if present:
        leg1_ok = not room.blocked(tx, body)
        leg2_ok = not room.blocked(body, rx)
        dS = (np.hypot(body[0]-tx[0], body[1]-tx[1])
              + np.hypot(rx[0]-body[0], rx[1]-body[1]) + 2.0*resp_disp)
        if leg1_ok and leg2_ok:
            a = 0.5/(dS + 0.1)
            h += a*np.exp(-1j*k2pi*freqs*dS/C)
        else:
            # direct scatter blocked -> breathing reaches via a diffracting edge (weak)
            for Cc in room.diffracting_edges():
                dsc = None
                if (not leg1_ok) and leg2_ok:
                    # Tx -> corner -> body -> Rx
                    if (not room.blocked(tx, Cc)) and (not room.blocked(Cc, body)):
                        dsc = (np.hypot(Cc[0]-tx[0], Cc[1]-tx[1])
                               + np.hypot(body[0]-Cc[0], body[1]-Cc[1])
                               + np.hypot(rx[0]-body[0], rx[1]-body[1]) + 2.0*resp_disp)
                elif leg1_ok and (not leg2_ok):
                    # Tx -> body -> corner -> Rx
                    if (not room.blocked(body, Cc)) and (not room.blocked(Cc, rx)):
                        dsc = (np.hypot(body[0]-tx[0], body[1]-tx[1])
                               + np.hypot(Cc[0]-body[0], Cc[1]-body[1])
                               + np.hypot(rx[0]-Cc[0], rx[1]-Cc[1]) + 2.0*resp_disp)
                if dsc is not None:
                    a = 0.5*0.22/(dsc + 0.1)      # diffracted scatter: much weaker
                    h += a*np.exp(-1j*k2pi*freqs*dsc/C)
    return h
