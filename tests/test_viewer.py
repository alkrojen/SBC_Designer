import os

import cadquery as cq
import numpy as np
import pytest

from sbc_designer.step_io import ModelPart
from sbc_designer.viewer import VIEW_DIRECTIONS, Scene, explode_direction, polydata_from_mesh


@pytest.fixture()
def scene():
    s = Scene(offscreen=True)
    s.render_window.SetSize(400, 300)
    s.add_part("box", ModelPart("box", cq.Solid.makeBox(100, 60, 2), (0, 0.5, 0)))
    s.add_part("cyl", ModelPart("cyl", cq.Solid.makeCylinder(5, 10, cq.Vector(20, 20, 2))), group="generated")
    s.set_view("iso")
    return s


def _cam(scene):
    c = scene.camera
    return np.array(c.GetPosition()), np.array(c.GetFocalPoint())


def test_polydata_from_mesh():
    v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
    t = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]])
    pd = polydata_from_mesh(v, t)
    assert pd.GetNumberOfPolys() == 4
    assert pd.GetPointData().GetNormals() is not None


def test_objects_bounds_and_fit(scene):
    b = scene.visible_bounds()
    assert b[0] == pytest.approx(0, abs=0.5) and b[1] == pytest.approx(100, abs=0.5)
    assert scene.keys("generated") == ["cyl"]
    scene.set_visible("cyl", False)
    assert scene.visible_bounds()[5] == pytest.approx(2, abs=0.2)
    scene.set_visible("cyl", True)


@pytest.mark.parametrize("name", list(VIEW_DIRECTIONS))
def test_view_presets(scene, name):
    scene.set_view(name)
    pos, fp = _cam(scene)
    d = (pos - fp) / np.linalg.norm(pos - fp)
    want = np.array(VIEW_DIRECTIONS[name][0], float)
    want /= np.linalg.norm(want)
    assert d == pytest.approx(want, abs=1e-6)
    assert fp == pytest.approx([50, 30, 6], abs=0.6)


def test_unknown_view(scene):
    with pytest.raises(ValueError):
        scene.set_view("sideways")


def test_zoom(scene):
    pos, fp = _cam(scene)
    d0 = np.linalg.norm(pos - fp)
    scene.zoom(2.0)
    pos, fp = _cam(scene)
    assert np.linalg.norm(pos - fp) == pytest.approx(d0 / 2, rel=1e-6)
    scene.zoom(0.5)
    pos, fp = _cam(scene)
    assert np.linalg.norm(pos - fp) == pytest.approx(d0, rel=1e-6)
    with pytest.raises(ValueError):
        scene.zoom(0)


def test_zoom_parallel(scene):
    scene.set_parallel(True)
    s0 = scene.camera.GetParallelScale()
    scene.zoom(2.0)
    assert scene.camera.GetParallelScale() == pytest.approx(s0 / 2)


def test_pan_moves_camera_and_focal_point_together(scene):
    scene.set_view("top")
    pos0, fp0 = _cam(scene)
    scene.pan(0.1, 0.0)  # scene moves right -> camera moves to -X
    pos1, fp1 = _cam(scene)
    assert (pos1 - pos0) == pytest.approx(fp1 - fp0)
    assert fp1[0] < fp0[0]
    assert fp1[1] == pytest.approx(fp0[1])
    scene.pan(0.0, 0.1)  # scene moves up -> camera moves to -Y
    pos2, fp2 = _cam(scene)
    assert fp2[1] < fp1[1]


def test_rotate_keeps_distance(scene):
    pos0, fp0 = _cam(scene)
    scene.rotate(azimuth=90)
    pos1, fp1 = _cam(scene)
    assert np.linalg.norm(pos1 - fp1) == pytest.approx(np.linalg.norm(pos0 - fp0))
    assert not np.allclose(pos0, pos1)
    scene.rotate(elevation=20, roll=10)
    pos2, fp2 = _cam(scene)
    assert np.linalg.norm(pos2 - fp2) == pytest.approx(np.linalg.norm(pos0 - fp0))


def test_opacity_and_explode(scene):
    scene.set_group_opacity("generated", 0.3)
    assert scene.objects["cyl"].actor.GetProperty().GetOpacity() == pytest.approx(0.3)
    scene.remove("cyl")
    part = ModelPart("tile", cq.Solid.makeBox(1, 1, 1), meta={"side": "bottom", "layer": 2})
    assert explode_direction(part) == (0, 0, -2)
    scene.add_part("tile", part, explode_dir=explode_direction(part))
    scene.set_explode(1.0)
    assert scene.objects["tile"].actor.GetPosition() == pytest.approx((0, 0, -2 * scene.explode_spacing))
    scene.set_explode(0)
    assert scene.objects["tile"].actor.GetPosition() == pytest.approx((0, 0, 0))
    assert explode_direction(ModelPart("x", part.shape)) == (0, 0, 0)


def test_remove_and_clear(scene):
    scene.remove("cyl")
    assert "cyl" not in scene.objects
    scene.clear()
    assert scene.objects == {}
    assert scene.visible_bounds() is None


def test_screenshot(scene, tmp_path):
    path = str(tmp_path / "shot.png")
    scene.screenshot(path)
    assert os.path.getsize(path) > 1000
    with open(path, "rb") as fh:
        assert fh.read(8) == b"\x89PNG\r\n\x1a\n"
