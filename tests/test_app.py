"""GUI tests (pytest-qt). They need a display: native on Windows/macOS, Xvfb on Linux."""

import os
import sys

import pytest

if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
    pytest.skip("GUI tests need a display (run under xvfb-run on Linux)", allow_module_level=True)

pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402

from scb_designer.app import MainWindow, ParametersDialog  # noqa: E402
from scb_designer.design import SCBParameters  # noqa: E402


@pytest.fixture()
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    yield w
    qtbot.waitUntil(lambda: not w.busy, timeout=120000)


def test_starts_with_design_disabled(win):
    assert not win.btn_all.isEnabled()
    assert not win.act_export_sel.isEnabled()


def test_load_view_generate_and_export(win, qtbot, small_step, tmp_path, monkeypatch):
    win.load(small_step)
    qtbot.waitUntil(lambda: not win.busy and bool(win.project.raw_parts), timeout=120000)
    assert win.tree_root_model.childCount() == len(win.project.raw_parts)
    assert win.btn_all.isEnabled()
    assert "keyed pockets" in win.report.toPlainText()

    # view operations through the toolbar actions
    for name in ("iso", "top", "bottom", "front", "fit"):
        win.view_actions[name].trigger()
    cam = win.scene.camera
    d0 = cam.GetDistance()
    win._cam(lambda s: s.zoom(2.0))
    assert cam.GetDistance() == pytest.approx(d0 / 2, rel=1e-3)

    # generate the alignment layer for the bottom side only
    win.side_combo.setCurrentIndex(1)
    win.part_buttons["alignment"].click()
    qtbot.waitUntil(lambda: not win.busy and bool(win.project.generated), timeout=120000)
    assert list(win.project.generated) == [("alignment", "bottom")]
    assert win.tree_root_gen.childCount() == 1
    node = win.tree_root_gen.child(0)
    key = node.child(0).data(0, Qt.UserRole + 1)
    node.child(0).setCheckState(0, Qt.Unchecked)
    assert not win.scene.objects[key].actor.GetVisibility()

    # export the ticked parts
    node.child(0).setCheckState(0, Qt.Checked)
    out = str(tmp_path / "gui_export.step")
    monkeypatch.setattr("scb_designer.app.QFileDialog.getSaveFileName", lambda *a, **k: (out, ""))
    win.export_checked()
    qtbot.waitUntil(lambda: not win.busy, timeout=120000)
    assert os.path.isfile(out)

    win.clear_generated()
    assert win.tree_root_gen.childCount() == 0 and not win.project.generated


def test_non_pcba_file_disables_design(win, qtbot, tmp_path):
    import cadquery as cq

    from scb_designer.step_io import ModelPart, export_step

    path = str(tmp_path / "cube.step")
    export_step([ModelPart("cube", cq.Solid.makeBox(10, 10, 10))], path)
    win.load(path)
    qtbot.waitUntil(lambda: not win.busy and bool(win.project.raw_parts), timeout=60000)
    assert not win.btn_all.isEnabled()
    assert "PCBA" in win.report.toPlainText()


def test_parameters_dialog_roundtrip(qtbot):
    p = SCBParameters()
    p.alignment_thickness = 1.25
    dlg = ParametersDialog(p)
    qtbot.addWidget(dlg)
    assert dlg.values().alignment_thickness == pytest.approx(1.25)
    dlg._defaults()
    assert dlg.values() == SCBParameters()
