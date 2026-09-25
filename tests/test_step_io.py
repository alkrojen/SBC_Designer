import os

import cadquery as cq
import pytest

from sbc_designer.step_io import ModelPart, StepReadError, export_step, load_step


def test_roundtrip_keeps_names_colors_and_geometry(tmp_path):
    parts = [
        ModelPart("box A", cq.Solid.makeBox(10, 5, 2), (0.9, 0.1, 0.1)),
        ModelPart("cyl B", cq.Solid.makeCylinder(2, 4, cq.Vector(20, 0, 0)), (0.1, 0.2, 0.9)),
    ]
    path = str(tmp_path / "rt.step")
    export_step(parts, path)
    assert os.path.getsize(path) > 0
    back = load_step(path)
    assert [p.name for p in back] == ["box A", "cyl B"]
    assert back[0].color == pytest.approx((0.9, 0.1, 0.1), abs=1e-3)
    assert back[1].color == pytest.approx((0.1, 0.2, 0.9), abs=1e-3)
    assert back[0].shape.Volume() == pytest.approx(100.0, rel=1e-6)
    bb = back[1].shape.BoundingBox()
    assert bb.xmin == pytest.approx(18.0, abs=1e-6)


def test_duplicate_names_are_made_unique(tmp_path):
    parts = [ModelPart("same", cq.Solid.makeBox(1, 1, 1)),
             ModelPart("same", cq.Solid.makeBox(1, 1, 1, cq.Vector(5, 0, 0)))]
    path = str(tmp_path / "dup.step")
    export_step(parts, path)
    names = [p.name for p in load_step(path)]
    assert len(set(names)) == 2


def test_plain_step_without_assembly_is_split_into_solids(tmp_path):
    path = str(tmp_path / "plain.step")
    comp = cq.Compound.makeCompound([cq.Solid.makeBox(1, 1, 1), cq.Solid.makeBox(1, 1, 1, cq.Vector(3, 0, 0))])
    cq.exporters.export(cq.Workplane().add(comp), path)
    parts = load_step(path)
    assert len(parts) == 2


def test_missing_file_raises():
    with pytest.raises(StepReadError):
        load_step("/nonexistent/file.step")


def test_garbage_file_raises(tmp_path):
    p = tmp_path / "bad.step"
    p.write_text("this is not a STEP file")
    with pytest.raises(StepReadError):
        load_step(str(p))


def test_export_nothing_raises(tmp_path):
    with pytest.raises(ValueError):
        export_step([], str(tmp_path / "x.step"))


def test_demo_file_loads(demo_parts):
    assert len(demo_parts) > 50
    names = [p.name for p in demo_parts]
    assert any("PCB" in n for n in names)
    assert any(n.startswith("U1 MCU") for n in names)
    assert all(p.shape.isValid() for p in demo_parts)
    assert all(p.color is not None for p in demo_parts)
