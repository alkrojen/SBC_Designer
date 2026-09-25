import cadquery as cq
import pytest

from sbc_designer.design import (ALIGNMENT, BOTH, COVER, PART_TYPES, PRESSING, SCREWS,
                                 SBCDesigner)
from sbc_designer.design.layout import THROUGH
from sbc_designer.pcba import BOTTOM, SIDES, TOP


def inside(shape, x, y, z):
    return any(s.isInside(cq.Vector(x, y, z), 1e-4) for s in shape.Solids())


def test_generate_all_returns_every_part(small_generated):
    keys = set(small_generated)
    expected = {(p, s) for p in (ALIGNMENT, PRESSING, COVER) for s in SIDES} | {(SCREWS, BOTH)}
    assert keys == expected
    for key, parts in small_generated.items():
        assert parts, key
        for p in parts:
            assert p.shape.isValid(), p.name
            assert p.shape.Volume() > 0.4, p.name
            assert p.meta["part"] == key[0]


def test_unknown_part_or_side(small_designer):
    with pytest.raises(ValueError):
        small_designer.generate("lid")
    with pytest.raises(ValueError):
        small_designer.generate(ALIGNMENT, "left")


@pytest.mark.parametrize("side", SIDES)
def test_parts_stack_in_z_order(small_generated, small_designer, side):
    z = small_designer.layout.z
    T = small_designer.pcba.thickness

    def zr(part):
        bb = small_generated[(part, side)][0].shape.BoundingBox()
        if len(small_generated[(part, side)]) > 1:
            for p in small_generated[(part, side)][1:]:
                bb = bb.add(p.shape.BoundingBox())
        return (bb.zmin, bb.zmax) if side == TOP else (T - bb.zmax, T - bb.zmin)

    a, p, c = zr(ALIGNMENT), zr(PRESSING), zr(COVER)
    assert a == pytest.approx((z.mid, z.press_top), abs=1e-4)
    # pressing bosses reach down into the pockets; tiles end at press_top
    assert p[1] == pytest.approx(z.press_top, abs=1e-4)
    assert z.board < p[0] < z.align_top
    assert c[0] == pytest.approx(z.press_top, abs=1e-4)
    assert c[1] >= z.cover_top - 1e-4


def test_alignment_has_keyed_pocket_with_datum_pads(small_generated, small_pcba, small_designer):
    shape = small_generated[(ALIGNMENT, TOP)][0].shape
    p = small_designer.params
    z = small_designer.layout.z
    f = next(f for f in small_pcba.features(TOP) if f.name.startswith("U1"))
    zm = z.board + 0.5
    # the pocket is empty where the part sits
    assert not inside(shape, f.rect.cx, f.rect.cy, zm)
    # clearance gap next to the long wall away from the pads
    gx, gy = f.rect.to_world(0.0, f.rect.width / 2 + p.pocket_clearance / 2)
    assert not inside(shape, gx, gy, zm)
    # datum pad on the other long wall (at L/4) is solid and touches the part
    px, py = f.rect.to_world(f.rect.length / 4, -(f.rect.width / 2 + p.pocket_clearance / 2))
    assert inside(shape, px, py, zm)
    # third datum on the short wall
    sx, sy = f.rect.to_world(-(f.rect.length / 2 + p.pocket_clearance / 2), 0.0)
    assert inside(shape, sx, sy, zm)
    # solid material well away from pockets and channels
    assert inside(shape, 55.0, 38.0, zm)


def test_alignment_frame_wraps_board_edge_and_has_screw_holes(small_generated, small_designer):
    shape = small_generated[(ALIGNMENT, TOP)][0].shape
    z = small_designer.layout.z
    # frame below board top level outside the board
    assert inside(shape, -8.0, 5.0, z.mid + 1.0)
    # the board itself is not overlapped
    assert not inside(shape, 5.0, 5.0, z.board - 0.1)
    for s in small_designer.layout.screws:
        assert not inside(shape, s.x, s.y, z.align_top - 0.5)


def test_bottom_alignment_has_lead_pockets(small_generated, small_pcba):
    shape = small_generated[(ALIGNMENT, BOTTOM)][0].shape
    T = small_pcba.thickness
    leads = [f for f in small_pcba.features(BOTTOM) if not f.owner]
    assert leads
    for f in leads:
        assert not inside(shape, f.rect.cx, f.rect.cy, -0.5)
    # bottom side is mirrored: material lies below the board
    bb = shape.BoundingBox()
    assert bb.zmax == pytest.approx(T / 2, abs=1e-4)
    assert bb.zmin < 0


def test_alignment_does_not_collide_with_components(small_generated, small_pcba):
    for side in SIDES:
        shape = small_generated[(ALIGNMENT, side)][0].shape
        for c in small_pcba.components:
            common = shape.intersect(c.part.shape)
            # datum pads touch the parts by design (10 um overlap at most)
            assert common.Volume() < 0.05, (side, c.name, common.Volume())


def test_pressing_tiles(small_generated, small_designer):
    tiles = small_generated[(PRESSING, TOP)]
    materials = [t.meta["material"] for t in tiles]
    assert materials.count("aluminium") == 1
    assert materials.count("polymer") >= 1
    assert all(t.shape.isValid() for t in tiles)
    lay = small_designer.layout
    # the tall electrolytic passes through the pressing layer
    c2 = next(f for f in lay.sides[TOP].features(THROUGH))
    assert not any(inside(t.shape, c2.rect.cx, c2.rect.cy, lay.z.align_top + 1.0) for t in tiles)
    # each sprung boss reaches below the alignment top to preload its part
    for a in lay.sides[TOP].arms:
        x, y = a.boss.center
        assert any(inside(t.shape, x, y, a.tip_z + 0.02) for t in tiles), a.feature.name


def test_cover_has_dome_ribs_and_port(small_generated, small_designer):
    cover = small_generated[(COVER, TOP)][0].shape
    lay = small_designer.layout
    z = lay.z
    c2 = next(f for f in lay.sides[TOP].features(THROUGH))
    top_c = z.board + c2.height
    # inside the dome is hollow, its roof is solid
    assert not inside(cover, c2.rect.cx, c2.rect.cy, top_c - 1.0)
    roof = top_c + lay.params.dome_clearance + lay.params.dome_wall / 2
    assert inside(cover, c2.rect.cx, c2.rect.cy, roof)
    px, py = lay.sides[TOP].port
    assert not inside(cover, px, py, z.skin_top - 0.5)
    assert inside(cover, px + lay.params.port_diameter / 2 + 0.7, py, z.skin_top - 0.5)
    bottom = small_generated[(COVER, BOTTOM)][0]
    assert "base plate" in bottom.name


def test_screw_grid(small_generated, small_designer):
    parts = small_generated[(SCREWS, BOTH)]
    n = len(small_designer.layout.screws)
    screws, nuts, sleeves = parts
    assert len(screws.shape.Solids()) == n
    assert len(nuts.shape.Solids()) == n
    assert len(sleeves.shape.Solids()) == 2 * n
    bb = screws.shape.BoundingBox()
    z = small_designer.layout.z
    assert bb.zmax > z.cover_top and bb.zmin < small_designer.pcba.thickness - z.cover_top


def test_each_part_can_be_generated_individually(small_pcba):
    d = SBCDesigner(small_pcba)
    for part in PART_TYPES:
        for side in SIDES:
            out = d.generate(part, side)
            assert out and all(p.shape.isValid() for p in out)


def test_demo_board_all_parts(demo_pcba_model, tmp_path):
    """Full demo run: every part on both sides, exported to STEP."""
    d = SBCDesigner(demo_pcba_model)
    res = d.generate_all()
    parts = [p for v in res.values() for p in v]
    assert all(p.shape.isValid() for p in parts)
    assert len(res[(PRESSING, TOP)]) >= 4
    path = d.export(parts, str(tmp_path / "demo_sbc.step"))
    assert (tmp_path / "demo_sbc.step").stat().st_size > 100000
