"""Analysis of a loaded PCBA: find the board, bring it into the canonical
frame and describe every component as it appears from each side.

Canonical frame: the board lies in the XY plane with its bottom face at
``z = 0`` and its top face at ``z = T`` (board thickness).  "Top" is +Z.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import cadquery as cq
import numpy as np
from OCP.gp import gp_Trsf

from .geometry2d import Rect, convex_hull, min_area_rect
from .step_io import ModelPart
from .tessellate import mesh_shape

TOP = "top"
BOTTOM = "bottom"
SIDES = (TOP, BOTTOM)

DEFAULT_POWER_KEYWORDS = ("D-PAK", "DPAK", "TO-252", "TO-263", "D2PAK", "TO-220",
                          "TO-247", "POWERPAK", "SOT-223")


class PCBAError(ValueError):
    """Raised when a model cannot be interpreted as a PCBA."""


@dataclass
class Feature:
    """What a component occupies on one side of the board (side-local)."""

    name: str
    component: int            # index into PCBA.components
    rect: Rect                # minimum-area footprint rectangle
    hull: np.ndarray          # convex hull of the footprint (Kx2)
    height: float             # extent above that side's board surface
    owner: bool               # True: the component body lives on this side
    power: bool = False       # needs a metal (thermal) pressing tile


@dataclass
class Component:
    name: str
    part: ModelPart
    side: str                 # owner side
    features: Dict[str, List[Feature]] = field(default_factory=dict)
    power: bool = False


@dataclass
class Hole:
    x: float
    y: float
    diameter: float


@dataclass
class PCBA:
    parts: List[ModelPart]            # all parts, in the canonical frame
    board: ModelPart
    thickness: float
    outline: np.ndarray               # board outer outline polygon (Nx2)
    outline_wire: cq.Wire             # same, as an OCC wire at z = 0
    holes: List[Hole]
    components: List[Component]
    transform: gp_Trsf                # applied to the original model

    @property
    def bounds(self) -> Tuple[float, float, float, float]:
        o = self.outline
        return (float(o[:, 0].min()), float(o[:, 1].min()),
                float(o[:, 0].max()), float(o[:, 1].max()))

    def features(self, side: str, owner: Optional[bool] = None) -> List[Feature]:
        out = []
        for c in self.components:
            for f in c.features.get(side, []):
                if owner is None or f.owner == owner:
                    out.append(f)
        return out

    def component_count(self, side: str) -> int:
        return sum(1 for c in self.components if c.side == side)


# --------------------------------------------------------------------------- #
def _dims(bb) -> np.ndarray:
    return np.array([bb.xlen, bb.ylen, bb.zlen])


def find_board(parts: Sequence[ModelPart]) -> int:
    """Index of the part that is the bare PCB.

    A candidate is a thin plate: smallest dimension <= 6 mm and < 15 % of the
    middle one. Names containing PCB/board win; otherwise the largest plate.
    """
    best, best_score = None, -1.0
    for i, p in enumerate(parts):
        d = np.sort(_dims(p.shape.BoundingBox()))
        if d[0] <= 0 or d[0] > 6.0 or d[0] > 0.15 * d[1]:
            continue
        score = d[1] * d[2]
        lname = p.name.lower()
        if "pcb" in lname or "board" in lname:
            score *= 100.0
        if score > best_score:
            best, best_score = i, score
    if best is None:
        raise PCBAError("No printed circuit board (thin plate) found in the model")
    return best


def canonical_transform(board_shape: cq.Shape) -> gp_Trsf:
    """Rotation/translation that puts the board's thin axis on Z, bottom z=0."""
    bb = board_shape.BoundingBox()
    thin = int(np.argmin(_dims(bb)))
    rot = gp_Trsf()
    # cyclic permutations are proper rotations (det = +1)
    if thin == 0:      # X thin: (x, y, z) -> (y, z, x)
        rot.SetValues(0, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0)
    elif thin == 1:    # Y thin: (x, y, z) -> (z, x, y)
        rot.SetValues(0, 0, 1, 0, 1, 0, 0, 0, 0, 1, 0, 0)
    moved = board_shape.transformShape(cq.Matrix(rot)) if thin != 2 else board_shape
    zmin = moved.BoundingBox().zmin
    tr = gp_Trsf()
    tr.SetTranslation(cq.Vector(0, 0, -zmin).wrapped)
    return tr.Multiplied(rot)


def _board_face(board: cq.Shape, thickness: float) -> cq.Face:
    faces = [f for f in board.Faces()
             if f.geomType() == "PLANE" and abs(abs(f.normalAt().z) - 1.0) < 1e-6]
    if not faces:
        raise PCBAError("Board has no planar face parallel to its plane")
    return max(faces, key=lambda f: f.Area())


def _wire_points(wire: cq.Wire, step: float = 1.0) -> np.ndarray:
    pts = []
    for e in wire.Edges():
        n = 1 if e.geomType() == "LINE" else max(4, int(math.ceil(e.Length() / step)))
        for i in range(n):
            p = e.positionAt(i / n)
            pts.append((p.x, p.y))
    return np.array(pts)


def _holes(face: cq.Face) -> List[Hole]:
    holes = []
    for w in face.innerWires():
        edges = w.Edges()
        if all(e.geomType() == "CIRCLE" for e in edges):
            r = edges[0].radius()
            c = edges[0].arcCenter()
            holes.append(Hole(c.x, c.y, 2 * r))
    return holes


def _footprint(points: np.ndarray) -> Tuple[Rect, np.ndarray]:
    xy = points[:, :2]
    return min_area_rect(xy), convex_hull(xy)


def cluster_points(points: np.ndarray, gap: float) -> List[np.ndarray]:
    """Split 3D points into groups whose XY gaps exceed ``gap`` (single link)."""
    n = len(points)
    if n == 0:
        return []
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    xy = points[:, :2]
    for i in range(n):
        d = np.hypot(*(xy[i + 1:] - xy[i]).T)
        for j in np.nonzero(d <= gap)[0]:
            a, b = find(i), find(i + 1 + int(j))
            if a != b:
                parent[a] = b
    groups: Dict[int, list] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return [points[idx] for idx in groups.values()]


def _solids(shape: cq.Shape) -> list:
    s = shape.Solids()
    return s if s else [shape]


def analyze(parts: Sequence[ModelPart], power_keywords: Sequence[str] = DEFAULT_POWER_KEYWORDS,
            mesh_tolerance: float = 0.05, lead_gap: float = 0.8) -> PCBA:
    """Identify the board and describe each component per side."""
    if not parts:
        raise PCBAError("Empty model")
    bi = find_board(parts)
    trsf = canonical_transform(parts[bi].shape)
    matrix = cq.Matrix(trsf)
    canon = [ModelPart(p.name, p.shape.transformShape(matrix), p.color, dict(p.meta)) for p in parts]
    board = canon[bi]
    bb = board.shape.BoundingBox()
    thickness = bb.zmax - bb.zmin
    face = _board_face(board.shape, thickness)
    outer = face.outerWire().translate(cq.Vector(0, 0, -face.Center().z))
    outline = _wire_points(outer)
    holes = _holes(face)

    keys = [k.upper() for k in power_keywords]
    eps = 1e-3
    components: List[Component] = []
    for i, p in enumerate(canon):
        if i == bi:
            continue
        power = any(k in p.name.upper() for k in keys)
        per_solid = []
        for s in _solids(p.shape):
            v, _ = mesh_shape(s, mesh_tolerance)
            if len(v):
                per_solid.append(v)
        if not per_solid:
            continue
        allv = np.vstack(per_solid)
        up = allv[:, 2].max() - thickness
        down = -allv[:, 2].min()
        owner_side = TOP if up >= down else BOTTOM
        comp = Component(p.name, p, owner_side, {TOP: [], BOTTOM: []}, power)
        idx = len(components)
        for side in SIDES:
            def side_pts(v):
                return v[v[:, 2] > thickness + eps] if side == TOP else v[v[:, 2] < -eps]

            def height(v):
                return float(v[:, 2].max() - thickness) if side == TOP else float(-v[:, 2].min())

            if side == owner_side:
                pts = side_pts(allv)
                if len(pts) >= 1:
                    rect, hull = _footprint(pts)
                    comp.features[side].append(
                        Feature(p.name, idx, rect, hull, height(pts), True, power))
            else:
                for pts in cluster_points(side_pts(allv), lead_gap):
                    if len(pts) >= 1:
                        rect, hull = _footprint(pts)
                        comp.features[side].append(
                            Feature(f"{p.name} (leads)", idx, rect, hull, height(pts), False, False))
        components.append(comp)

    return PCBA(canon, board, float(thickness), outline, outer, holes, components, trsf)
