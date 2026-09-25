"""Triangulation of OpenCASCADE shapes into numpy arrays."""

from __future__ import annotations

from typing import Tuple

import cadquery as cq
import numpy as np


def mesh_shape(shape: cq.Shape, tolerance: float = 0.05,
               angular_tolerance: float = 0.3) -> Tuple[np.ndarray, np.ndarray]:
    """Return ``(vertices Nx3 float, triangles Mx3 int)`` for ``shape``."""
    verts, tris = shape.tessellate(tolerance, angular_tolerance)
    v = np.array([(p.x, p.y, p.z) for p in verts], dtype=float).reshape(-1, 3)
    t = np.array(tris, dtype=np.int64).reshape(-1, 3)
    return v, t


def adaptive_tolerance(shape: cq.Shape, rel: float = 1e-3, lo: float = 0.01,
                       hi: float = 0.5) -> float:
    """Chordal deflection proportional to the shape size, clamped."""
    bb = shape.BoundingBox()
    return float(min(max(bb.DiagonalLength * rel, lo), hi))
