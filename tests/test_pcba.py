import cadquery as cq
import numpy as np
import pytest

from sbc_designer.pcba import BOTTOM, TOP, PCBAError, analyze, cluster_points, find_board
from sbc_designer.step_io import ModelPart


def _comp(pcba, prefix):
    return next(c for c in pcba.components if c.name.startswith(prefix))


def test_small_board_is_found_and_measured(small_pcba):
    assert small_pcba.board.name.startswith("PCB")
    assert small_pcba.thickness == pytest.approx(1.6)
    assert small_pcba.bounds == pytest.approx((0, 0, 60, 40))
    assert len(small_pcba.holes) == 1
    h = small_pcba.holes[0]
    assert (h.x, h.y, h.diameter) == pytest.approx((30, 20, 3.2))


def test_component_sides_and_heights(small_pcba):
    assert _comp(small_pcba, "R1").side == TOP
    assert _comp(small_pcba, "Q2").side == BOTTOM
    assert _comp(small_pcba, "R2").side == BOTTOM
    r1 = _comp(small_pcba, "R1").features[TOP][0]
    assert r1.owner
    assert r1.height == pytest.approx(0.45, abs=1e-3)
    assert r1.rect.length == pytest.approx(1.6, abs=1e-3)
    assert r1.rect.width == pytest.approx(0.8, abs=1e-3)


def test_rotated_part_footprint(small_pcba):
    c1 = _comp(small_pcba, "C1").features[TOP][0]
    assert c1.rect.angle == pytest.approx(30.0, abs=1e-3)
    assert c1.rect.length == pytest.approx(2.0, abs=1e-3)


def test_through_hole_leads_become_features_on_the_other_side(small_pcba):
    c2 = _comp(small_pcba, "C2")
    assert c2.side == TOP
    leads = c2.features[BOTTOM]
    assert len(leads) == 2 and not any(f.owner for f in leads)
    assert all(f.height == pytest.approx(1.5, abs=1e-3) for f in leads)
    xs = sorted(f.rect.cx for f in leads)
    assert xs == pytest.approx([18.25, 21.75], abs=1e-2)


def test_power_package_detected(small_pcba):
    assert _comp(small_pcba, "Q1").power
    assert not _comp(small_pcba, "U1").power


def test_demo_board(demo_pcba_model):
    p = demo_pcba_model
    assert p.thickness == pytest.approx(1.6)
    assert p.bounds == pytest.approx((0, 0, 160, 100))
    assert len(p.holes) == 5
    assert p.component_count(TOP) >= 60
    assert p.component_count(BOTTOM) >= 10
    assert _comp(p, "K1").side == TOP
    assert _comp(p, "U6").side == BOTTOM


def test_vertical_board_is_brought_into_canonical_frame(small_parts):
    """Rotate the whole model so that the board stands on its edge (thin in X)."""
    rotated = [ModelPart(p.name, p.shape.rotate(cq.Vector(), cq.Vector(0, 1, 0), 90), p.color)
               for p in small_parts]
    p = analyze(rotated)
    assert p.thickness == pytest.approx(1.6, abs=1e-6)
    bb = p.board.shape.BoundingBox()
    assert bb.zmin == pytest.approx(0, abs=1e-6) and bb.zmax == pytest.approx(1.6, abs=1e-6)
    assert sorted([bb.xlen, bb.ylen]) == pytest.approx([40, 60])
    tops = sum(1 for c in p.components if c.side == TOP)
    bottoms = sum(1 for c in p.components if c.side == BOTTOM)
    assert {tops, bottoms} == {5, 2}


def test_no_board_raises():
    parts = [ModelPart("cube", cq.Solid.makeBox(10, 10, 10))]
    with pytest.raises(PCBAError):
        find_board(parts)
    with pytest.raises(PCBAError):
        analyze(parts)
    with pytest.raises(PCBAError):
        analyze([])


def test_named_board_preferred_over_bigger_plate():
    parts = [ModelPart("heatsink plate", cq.Solid.makeBox(200, 200, 2)),
             ModelPart("Main PCB", cq.Solid.makeBox(50, 50, 1.6))]
    assert find_board(parts) == 1


def test_cluster_points():
    pts = np.array([[0, 0, 0], [0.3, 0, 0], [5, 5, 0], [5.2, 5.1, 0], [20, 0, 0]], float)
    groups = cluster_points(pts, 0.8)
    assert sorted(len(g) for g in groups) == [1, 2, 2]
    assert cluster_points(np.zeros((0, 3)), 1.0) == []
