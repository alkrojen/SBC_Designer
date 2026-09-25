import dataclasses
import math

import pytest

from scb_designer.design.layout import (ARM, RECESS, THROUGH, classify, compute_layout,
                                        z_levels)
from scb_designer.design.params import SCBParameters
from scb_designer.geometry2d import Rect
from scb_designer.pcba import BOTTOM, SIDES, TOP, Feature


def test_z_levels():
    z = z_levels(1.6, SCBParameters())
    assert z.mid == pytest.approx(0.8)
    assert z.align_top == pytest.approx(3.6)
    assert z.press_top == pytest.approx(6.6)
    assert z.skin_top == pytest.approx(7.8)
    assert z.cover_top == pytest.approx(12.8)


@pytest.mark.parametrize("h,mode", [(0.45, ARM), (1.7, ARM), (1.8, RECESS), (3.5, RECESS),
                                    (3.8, THROUGH), (12.0, THROUGH)])
def test_classify(h, mode):
    f = Feature("x", 0, Rect(0, 0, 1, 1), None, h, True)
    assert classify(f, SCBParameters()) == mode


def test_perimeter_screws(small_pcba):
    lay = compute_layout(small_pcba)
    p = lay.params
    x0, y0, x1, y1 = lay.outer
    assert (x0, y0, x1, y1) == pytest.approx((-14, -14, 74, 54))
    per = [s for s in lay.screws if not s.interior]
    # all on the screw line, none duplicated, pitch within the limit
    for s in per:
        d = min(abs(s.x - (x0 + p.screw_edge_offset)), abs(s.x - (x1 - p.screw_edge_offset)),
                abs(s.y - (y0 + p.screw_edge_offset)), abs(s.y - (y1 - p.screw_edge_offset)))
        assert d == pytest.approx(0, abs=1e-6)
    assert len({(round(s.x, 3), round(s.y, 3)) for s in per}) == len(per)
    bottom_row = sorted(s.x for s in per if abs(s.y - (y0 + p.screw_edge_offset)) < 1e-6)
    assert max(b - a for a, b in zip(bottom_row, bottom_row[1:])) <= p.screw_pitch + 1e-6


def test_interior_screw_at_existing_hole(small_pcba):
    lay = compute_layout(small_pcba)
    interior = [s for s in lay.screws if s.interior]
    assert [(s.x, s.y) for s in interior] == [pytest.approx((30, 20))]


def test_interior_screw_modes(small_pcba):
    none = compute_layout(small_pcba, dataclasses.replace(SCBParameters(), interior_screws="none"))
    assert not any(s.interior for s in none.screws)
    grid = compute_layout(small_pcba, dataclasses.replace(SCBParameters(), interior_screws="grid",
                                                          screw_pitch=15.0))
    interior = [s for s in grid.screws if s.interior]
    assert interior, "expected at least one grid screw on the small board"
    feats = small_pcba.features(TOP) + small_pcba.features(BOTTOM)
    for s in interior:
        assert all(f.rect.distance_to_point((s.x, s.y)) >= grid.params.sleeve_od / 2 for f in feats)
    assert any("drilled" in w for w in grid.warnings)


def test_modes_and_arm_plans(small_pcba):
    lay = compute_layout(small_pcba)
    top = lay.sides[TOP]
    names = {f.name.split()[0]: top.mode[id(f)] for f in top.features()}
    assert names["R1"] == ARM
    assert names["U1"] == RECESS  # 1.75 mm SO-8 rises into the pressing layer
    assert names["C2"] == THROUGH
    kinds = {a.feature.name.split()[0]: a.kind for a in top.arms}
    assert kinds["Q1"] == "metal"
    assert kinds["R1"] == "cantilever"
    assert len(top.metal) == 1
    # every boss presses the part by the preload interference
    for a in top.arms:
        assert a.tip_z == pytest.approx(lay.z.board + a.feature.height - lay.params.preload_interference)
        assert a.contact_z >= lay.z.align_top - 1e-9


def test_arm_regions_do_not_overlap(demo_pcba_model):
    lay = compute_layout(demo_pcba_model)
    for side in SIDES:
        regions = [a.region for a in lay.sides[side].arms if a.region is not None]
        assert regions
        for i, a in enumerate(regions):
            for b in regions[i + 1:]:
                assert not a.overlaps(b)


def test_tile_splits_avoid_metal_tiles(demo_pcba_model):
    lay = compute_layout(demo_pcba_model)
    for side in SIDES:
        sl = lay.sides[side]
        bx0, by0, bx1, by1 = demo_pcba_model.bounds
        assert len(sl.split_x) == math.ceil((bx1 - bx0) / lay.params.tile_max_size) - 1
        for m in sl.metal:
            x0, y0, x1, y1 = m.bounds()
            assert not any(x0 < x < x1 for x in sl.split_x)
            assert not any(y0 < y < y1 for y in sl.split_y)


def test_getter_volume_and_channels(small_pcba):
    lay = compute_layout(small_pcba)
    p = lay.params
    for side in SIDES:
        sl = lay.sides[side]
        assert sl.getter_volume >= p.getter_volume_ml * 1000 - 1e-6
        # getters and port lie in the frame, outside the board
        bx0, by0, bx1, by1 = small_pcba.bounds
        for g in sl.getters + [Rect(sl.port[0], sl.port[1], 0.1, 0.1)]:
            gx0, gy0, gx1, gy1 = g.bounds()
            assert gx1 < bx0 or gx0 > bx1 or gy1 < by0 or gy0 > by1
        # one channel per edge of a spanning tree over pockets + getters + port
        assert len(sl.channels) == len(sl.keyed) + len(sl.getters)


def test_getter_too_big_warns(small_pcba):
    lay = compute_layout(small_pcba, dataclasses.replace(SCBParameters(), getter_volume_ml=20.0))
    assert any("Getter volume" in w for w in lay.sides[TOP].warnings)
