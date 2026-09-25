import math

import numpy as np
import pytest

from scb_designer.geometry2d import (Rect, convex_hull, distance_to_polygon_edge, evenly_spaced,
                                     min_area_rect, minimum_spanning_tree, point_in_polygon,
                                     polygon_area, segment_rect)


def test_convex_hull_square_with_interior_points():
    pts = [(0, 0), (1, 0), (1, 1), (0, 1), (0.5, 0.5), (0.2, 0.7), (1, 0.5)]
    hull = convex_hull(pts)
    assert len(hull) == 4
    assert polygon_area(hull) == pytest.approx(1.0)  # counter-clockwise -> positive


def test_convex_hull_degenerate():
    assert len(convex_hull([(1, 1)])) == 1
    assert len(convex_hull([(1, 1), (1, 1)])) == 1


@pytest.mark.parametrize("angle", [0.0, 17.0, 45.0, 90.0, 123.0])
def test_min_area_rect_recovers_rotated_rectangle(angle):
    r = Rect(5.0, -3.0, 4.0, 1.5, angle)
    rng = np.random.default_rng(1)
    inner = [r.to_world(x, y) for x, y in rng.uniform(-0.5, 0.5, (40, 2)) * [4.0, 1.5]]
    found = min_area_rect(np.vstack([r.corners(), inner]))
    assert found.length == pytest.approx(4.0, abs=1e-6)
    assert found.width == pytest.approx(1.5, abs=1e-6)
    assert found.cx == pytest.approx(5.0) and found.cy == pytest.approx(-3.0)
    assert (found.angle - angle % 180) % 180 == pytest.approx(0.0, abs=1e-6) or \
        abs((found.angle - angle) % 180 - 180) < 1e-6


def test_min_area_rect_length_is_longest_side():
    r = min_area_rect([(0, 0), (1, 0), (1, 5), (0, 5)])
    assert r.length == pytest.approx(5)
    assert r.width == pytest.approx(1)
    assert r.angle == pytest.approx(90)


def test_rect_geometry():
    r = Rect(0, 0, 4, 2, 0)
    assert r.area == 8
    assert r.contains((1.9, 0.9))
    assert not r.contains((2.1, 0))
    assert r.distance_to_point((5, 0)) == pytest.approx(3)
    assert r.distance_to_point((0, 0)) == 0
    assert r.expanded(1).length == 6 and r.expanded(1).width == 4
    assert r.bounds() == pytest.approx((-2, -1, 2, 1))


def test_rect_overlap_separating_axis():
    a = Rect(0, 0, 4, 2, 0)
    assert a.overlaps(Rect(3, 0, 4, 2, 0))
    assert not a.overlaps(Rect(4.5, 0, 4, 2, 0))
    assert not a.overlaps(Rect(4, 0, 4, 2, 0))  # touching
    # a rotated square whose bounding box overlaps but which does not
    assert not Rect(0, 0, 2, 2, 0).overlaps(Rect(2.5, 2.5, 2, 2, 45))
    assert Rect(0, 0, 2, 2, 0).overlaps(Rect(1.5, 1.5, 2, 2, 45))


def test_mst_is_spanning_and_minimal():
    pts = [(0, 0), (1, 0), (2, 0), (2, 1), (10, 10)]
    edges = minimum_spanning_tree(pts)
    assert len(edges) == len(pts) - 1
    # connectivity
    seen, stack = {0}, [0]
    adj = {i: set() for i in range(len(pts))}
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    while stack:
        for n in adj[stack.pop()]:
            if n not in seen:
                seen.add(n)
                stack.append(n)
    assert seen == set(range(len(pts)))
    total = sum(math.dist(pts[a], pts[b]) for a, b in edges)
    assert total == pytest.approx(3 + math.dist((2, 1), (10, 10)))


def test_mst_avoids_blocked_edges_when_possible():
    pts = [(0, 0), (1, 0), (0, 1)]
    edges = minimum_spanning_tree(pts, blocked=lambda i, j: {i, j} == {0, 1})
    assert (0, 1) not in edges and (1, 0) not in edges
    assert len(edges) == 2


def test_mst_small_inputs():
    assert minimum_spanning_tree([]) == []
    assert minimum_spanning_tree([(1, 2)]) == []


def test_point_in_polygon_and_edge_distance():
    sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert point_in_polygon((5, 5), sq)
    assert not point_in_polygon((11, 5), sq)
    assert distance_to_polygon_edge((5, 5), sq) == pytest.approx(5)
    assert distance_to_polygon_edge((12, 5), sq) == pytest.approx(2)


def test_segment_rect_covers_segment():
    r = segment_rect((0, 0), (10, 0), 1.5)
    assert r.length == pytest.approx(10) and r.width == pytest.approx(1.5)
    assert r.contains((0, 0)) and r.contains((10, 0))
    r2 = segment_rect((0, 0), (0, 0.2), 1.5)  # shorter than wide
    assert r2.length >= r2.width


def test_evenly_spaced():
    xs = evenly_spaced(0, 100, 30)
    assert xs[0] == 0 and xs[-1] == 100
    assert max(np.diff(xs)) <= 30 + 1e-9
    assert len(xs) == 5
    assert evenly_spaced(5, 5, 30) == [5]
