"""Small, dependency-free 2D geometry helpers used by the SBC layout code."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

import numpy as np

Point = Tuple[float, float]


def convex_hull(points) -> np.ndarray:
    """Convex hull (Andrew's monotone chain), counter-clockwise, no repeats."""
    pts = np.unique(np.asarray(points, dtype=float).reshape(-1, 2), axis=0)
    if len(pts) <= 2:
        return pts
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 1e-12:
            lower.pop()
        lower.append(tuple(p))
    upper: list = []
    for p in pts[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 1e-12:
            upper.pop()
        upper.append(tuple(p))
    return np.array(lower[:-1] + upper[:-1])


def polygon_area(poly) -> float:
    p = np.asarray(poly, dtype=float)
    if len(p) < 3:
        return 0.0
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


@dataclass(frozen=True)
class Rect:
    """Rotated rectangle. ``length`` >= ``width``; ``angle`` (deg) is the
    direction of the length axis measured from +X, normalised to [0, 180)."""

    cx: float
    cy: float
    length: float
    width: float
    angle: float = 0.0

    @property
    def center(self) -> Point:
        return (self.cx, self.cy)

    @property
    def area(self) -> float:
        return self.length * self.width

    @property
    def axes(self) -> Tuple[np.ndarray, np.ndarray]:
        a = math.radians(self.angle)
        u = np.array([math.cos(a), math.sin(a)])
        v = np.array([-math.sin(a), math.cos(a)])
        return u, v

    def corners(self) -> np.ndarray:
        u, v = self.axes
        c = np.array([self.cx, self.cy])
        hl, hw = self.length / 2, self.width / 2
        return np.array([c - u * hl - v * hw, c + u * hl - v * hw,
                         c + u * hl + v * hw, c - u * hl + v * hw])

    def expanded(self, d: float) -> "Rect":
        return Rect(self.cx, self.cy, max(self.length + 2 * d, 1e-6),
                    max(self.width + 2 * d, 1e-6), self.angle)

    def to_world(self, lx: float, ly: float) -> Point:
        """Rect-local (along length, along width) -> world coordinates."""
        u, v = self.axes
        p = np.array([self.cx, self.cy]) + u * lx + v * ly
        return (float(p[0]), float(p[1]))

    def contains(self, p: Point, tol: float = 1e-9) -> bool:
        u, v = self.axes
        d = np.array(p) - np.array([self.cx, self.cy])
        return abs(d @ u) <= self.length / 2 + tol and abs(d @ v) <= self.width / 2 + tol

    def distance_to_point(self, p: Point) -> float:
        """0 inside, else Euclidean distance to the rectangle."""
        u, v = self.axes
        d = np.array(p) - np.array([self.cx, self.cy])
        dx = max(abs(d @ u) - self.length / 2, 0.0)
        dy = max(abs(d @ v) - self.width / 2, 0.0)
        return math.hypot(dx, dy)

    def overlaps(self, other: "Rect", tol: float = 0.0) -> bool:
        """Separating-axis test; touching counts as not overlapping."""
        a, b = self.corners(), other.corners()
        for axis in (*self.axes, *other.axes):
            pa, pb = a @ axis, b @ axis
            if pa.max() <= pb.min() + tol or pb.max() <= pa.min() + tol:
                return False
        return True

    def bounds(self) -> Tuple[float, float, float, float]:
        c = self.corners()
        return float(c[:, 0].min()), float(c[:, 1].min()), float(c[:, 0].max()), float(c[:, 1].max())


def min_area_rect(points) -> Rect:
    """Minimum-area enclosing rectangle via rotating calipers over hull edges."""
    hull = convex_hull(points)
    if len(hull) == 0:
        raise ValueError("no points")
    if len(hull) == 1:
        return Rect(float(hull[0, 0]), float(hull[0, 1]), 1e-6, 1e-6, 0.0)
    best = None
    n = len(hull)
    for i in range(n if n > 2 else 1):
        e = hull[(i + 1) % n] - hull[i]
        norm = np.hypot(*e)
        if norm < 1e-12:
            continue
        u = e / norm
        v = np.array([-u[1], u[0]])
        pu, pv = hull @ u, hull @ v
        area = (pu.max() - pu.min()) * (pv.max() - pv.min())
        if best is None or area < best[0] - 1e-9:
            best = (area, u, v, pu.min(), pu.max(), pv.min(), pv.max())
    _, u, v, u0, u1, v0, v1 = best
    c = u * (u0 + u1) / 2 + v * (v0 + v1) / 2
    lu, lv = u1 - u0, v1 - v0
    ang = math.degrees(math.atan2(u[1], u[0]))
    if lv > lu + 1e-9:
        lu, lv = lv, lu
        ang += 90.0
    ang = _snap_angle(ang % 180.0)
    return Rect(float(c[0]), float(c[1]), float(lu), float(lv), ang)


def _snap_angle(a: float, tol: float = 1e-6) -> float:
    for s in (0.0, 90.0, 180.0):
        if abs(a - s) < tol:
            return 0.0 if s == 180.0 else s
    return a


def minimum_spanning_tree(points: Sequence[Point], blocked=None) -> List[Tuple[int, int]]:
    """Prim's algorithm on the complete Euclidean graph. Returns index pairs.

    ``blocked(i, j) -> bool`` may veto an edge; it is then only used if the
    graph cannot be connected otherwise (it gets a large penalty).
    """
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    n = len(pts)
    if n < 2:
        return []
    w = np.hypot(pts[:, None, 0] - pts[None, :, 0], pts[:, None, 1] - pts[None, :, 1])
    if blocked is not None:
        penalty = 1e6 + w.max()
        for i in range(n):
            for j in range(i + 1, n):
                if blocked(i, j):
                    w[i, j] += penalty
                    w[j, i] += penalty
    in_tree = np.zeros(n, dtype=bool)
    in_tree[0] = True
    dist = w[0].copy()
    parent = np.zeros(n, dtype=int)
    edges = []
    for _ in range(n - 1):
        d = np.where(in_tree, np.inf, dist)
        j = int(np.argmin(d))
        edges.append((int(parent[j]), j))
        in_tree[j] = True
        closer = w[j] < dist
        dist = np.where(closer, w[j], dist)
        parent = np.where(closer, j, parent)
    return edges


def point_in_polygon(p: Point, poly) -> bool:
    """Even-odd rule."""
    x, y = p
    pts = np.asarray(poly, dtype=float)
    inside = False
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xi:
                inside = not inside
    return inside


def distance_to_polygon_edge(p: Point, poly) -> float:
    pts = np.asarray(poly, dtype=float)
    q = np.asarray(p, dtype=float)
    best = math.inf
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        ab = b - a
        t = 0.0 if not ab.any() else float(np.clip((q - a) @ ab / (ab @ ab), 0.0, 1.0))
        best = min(best, float(np.hypot(*(a + t * ab - q))))
    return best


def segment_rect(p0: Point, p1: Point, width: float) -> Rect:
    """Rectangle covering the segment p0-p1 with the given width."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy)
    ang = math.degrees(math.atan2(dy, dx)) % 180.0
    return Rect((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, max(length, 1e-6), width, ang) \
        if length >= width else Rect((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, width, max(length, 1e-6), (ang + 90) % 180)


def evenly_spaced(start: float, end: float, max_pitch: float) -> List[float]:
    """Positions from start to end inclusive with spacing <= max_pitch."""
    span = end - start
    if span <= 0:
        return [start]
    n = max(1, math.ceil(span / max_pitch - 1e-9))
    return [start + span * i / n for i in range(n + 1)]
