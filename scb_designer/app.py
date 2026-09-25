"""SCB Designer main window (PySide6 + VTK)."""

from __future__ import annotations

import dataclasses
import os
import sys
import traceback
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QSettings, Qt, QThread, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider,
                               QTabWidget, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from . import __version__
from .demo_pcba import default_demo_path
from .design import BOTH, PART_LABELS, PART_TYPES, SCREWS, SIDE_LABELS, SCBParameters
from .pcba import SIDES
from .project import Project
from .step_io import ModelPart
from .viewer import ViewerWidget, explode_direction, part_polydata

APP_NAME = "SCB Designer"
KEY_ROLE = Qt.UserRole + 1


# --------------------------------------------------------------------------- #
class _Worker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], object]):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self.finished.emit(self._fn())
        except Exception as exc:  # report every failure to the GUI
            traceback.print_exc()
            self.failed.emit(f"{type(exc).__name__}: {exc}")


def _tessellate(parts: List[ModelPart]):
    return [(p, part_polydata(p)) for p in parts]


# --------------------------------------------------------------------------- #
class ParametersDialog(QDialog):
    """Form generated from the SCBParameters dataclass metadata."""

    def __init__(self, params: SCBParameters, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SCB design parameters")
        self._widgets: Dict[str, QWidget] = {}
        tabs = QTabWidget()
        groups: Dict[str, QFormLayout] = {}
        for f in dataclasses.fields(params):
            md = f.metadata
            group = md.get("group", "General")
            if group not in groups:
                page = QWidget()
                groups[group] = QFormLayout(page)
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setWidget(page)
                tabs.addTab(scroll, group)
            value = getattr(params, f.name)
            if f.name == "interior_screws":
                w = QComboBox()
                w.addItems(["existing_holes", "grid", "none"])
                w.setCurrentText(value)
            elif isinstance(value, str):
                w = QLineEdit(value)
            else:
                w = QDoubleSpinBox()
                w.setDecimals(3)
                w.setRange(md.get("min") if md.get("min") is not None else -1e6,
                           md.get("max") if md.get("max") is not None else 1e6)
                w.setSingleStep(0.1)
                w.setValue(value)
                if md.get("unit"):
                    w.setSuffix(f" {md['unit']}")
            if md.get("help"):
                w.setToolTip(md["help"])
            self._widgets[f.name] = w
            groups[group].addRow(md.get("label", f.name), w)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel
                                   | QDialogButtonBox.RestoreDefaults)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self._defaults)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)
        self.resize(520, 480)
        self.result_params: Optional[SCBParameters] = None

    def _set(self, params: SCBParameters):
        for name, w in self._widgets.items():
            v = getattr(params, name)
            if isinstance(w, QComboBox):
                w.setCurrentText(v)
            elif isinstance(w, QLineEdit):
                w.setText(v)
            else:
                w.setValue(v)

    def _defaults(self):
        self._set(SCBParameters())

    def values(self) -> SCBParameters:
        d = {}
        for name, w in self._widgets.items():
            if isinstance(w, QComboBox):
                d[name] = w.currentText()
            elif isinstance(w, QLineEdit):
                d[name] = w.text()
            else:
                d[name] = w.value()
        return SCBParameters.from_dict(d)

    def _accept(self):
        try:
            p = self.values()
            p.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid parameters", str(exc))
            return
        self.result_params = p
        self.accept()


# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    # (callback, argument): emitted from worker threads, delivered in the GUI thread
    _dispatch = Signal(object, object)

    def __init__(self):
        super().__init__()
        self._dispatch.connect(self._on_dispatch, Qt.QueuedConnection)
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1400, 900)
        self.project = Project()
        self._threads: List[Tuple[QThread, _Worker]] = []
        self._busy = 0

        self.viewer = ViewerWidget(self)
        self.scene = self.viewer.scene
        self.setCentralWidget(self.viewer)

        self._build_actions()
        self._build_model_dock()
        self._build_design_dock()
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumWidth(160)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().showMessage("Open a STEP file (Ctrl+O) or load the demo PCBA.")
        self._update_enabled()

    # ---------------------------------------------------------------- UI
    def _action(self, text, slot, shortcut=None, tip=None):
        a = QAction(text, self)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setStatusTip(tip)
        return a

    def _build_actions(self):
        m = self.menuBar()
        fm = m.addMenu("&File")
        self.act_open = self._action("&Open STEP...", self.open_dialog, "Ctrl+O", "Load a PCBA STEP file")
        self.act_demo = self._action("Load &demo PCBA", self.load_demo, "Ctrl+D",
                                     "Air-conditioner controller demo board")
        self.act_export_sel = self._action("&Export checked generated parts...", self.export_checked, "Ctrl+E")
        self.act_export_each = self._action("Export each generated part to &folder...", self.export_each)
        self.act_shot = self._action("Save &screenshot...", self.save_screenshot)
        self.act_load_params = self._action("Load parameters...", self.load_params)
        self.act_save_params = self._action("Save parameters...", self.save_params)
        for a in (self.act_open, self.act_demo, None, self.act_export_sel, self.act_export_each, None,
                  self.act_load_params, self.act_save_params, None, self.act_shot):
            fm.addSeparator() if a is None else fm.addAction(a)
        fm.addSeparator()
        fm.addAction(self._action("E&xit", self.close, "Ctrl+Q"))

        vm = m.addMenu("&View")
        tb = QToolBar("View")
        tb.setObjectName("viewToolbar")
        self.addToolBar(tb)
        tb.addAction(self.act_open)
        tb.addAction(self.act_demo)
        tb.addSeparator()
        self.view_actions = {}
        for name, key in (("fit", "F"), ("iso", "0"), ("top", "1"), ("bottom", "2"), ("front", "3"),
                          ("back", "4"), ("left", "5"), ("right", "6")):
            label = "Fit all" if name == "fit" else name.capitalize()
            a = self._action(label, (lambda _checked=False, n=name: self.set_view(n)), key, f"{label} view")
            self.view_actions[name] = a
            vm.addAction(a)
            tb.addAction(a)
        vm.addSeparator()
        tb.addSeparator()
        for label, slot, key in (("Zoom in", lambda: self._cam(lambda s: s.zoom(1.25)), "+"),
                                 ("Zoom out", lambda: self._cam(lambda s: s.zoom(0.8)), "-"),
                                 ("Pan left", lambda: self._cam(lambda s: s.pan(-0.1, 0)), "Left"),
                                 ("Pan right", lambda: self._cam(lambda s: s.pan(0.1, 0)), "Right"),
                                 ("Pan up", lambda: self._cam(lambda s: s.pan(0, 0.1)), "Up"),
                                 ("Pan down", lambda: self._cam(lambda s: s.pan(0, -0.1)), "Down"),
                                 ("Rotate left", lambda: self._cam(lambda s: s.rotate(azimuth=-15)), "Ctrl+Left"),
                                 ("Rotate right", lambda: self._cam(lambda s: s.rotate(azimuth=15)), "Ctrl+Right"),
                                 ("Tilt up", lambda: self._cam(lambda s: s.rotate(elevation=15)), "Ctrl+Up"),
                                 ("Tilt down", lambda: self._cam(lambda s: s.rotate(elevation=-15)), "Ctrl+Down")):
            a = self._action(label, slot, key)
            vm.addAction(a)
            if label.startswith("Zoom"):
                tb.addAction(a)
        self.act_parallel = self._action("Orthographic projection", self.toggle_parallel, "P")
        self.act_parallel.setCheckable(True)
        vm.addAction(self.act_parallel)
        tb.addAction(self.act_parallel)

        hm = m.addMenu("&Help")
        hm.addAction(self._action("&Mouse and keys", self.show_help, "F1"))
        hm.addAction(self._action("&About", self.show_about))

    def _build_model_dock(self):
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Model"])
        self.tree.itemChanged.connect(self._item_changed)
        self.tree_root_model = QTreeWidgetItem(["PCBA"])
        self.tree_root_gen = QTreeWidgetItem(["Generated SCB parts"])
        for root in (self.tree_root_model, self.tree_root_gen):
            root.setFlags(root.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            root.setCheckState(0, Qt.Checked)
            self.tree.addTopLevelItem(root)
        dock = QDockWidget("Model", self)
        dock.setObjectName("modelDock")
        dock.setWidget(self.tree)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

    def _build_design_dock(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        box = QGroupBox("Generate SCB phase-1 parts")
        bl = QVBoxLayout(box)
        row = QHBoxLayout()
        row.addWidget(QLabel("PCB side:"))
        self.side_combo = QComboBox()
        self.side_combo.addItem("Top", ["top"])
        self.side_combo.addItem("Bottom", ["bottom"])
        self.side_combo.addItem("Both sides", ["top", "bottom"])
        row.addWidget(self.side_combo, 1)
        bl.addLayout(row)
        self.part_buttons = {}
        for part in PART_TYPES:
            b = QPushButton(f"Generate {PART_LABELS[part].lower()}")
            b.clicked.connect(lambda _=False, p=part: self.generate([p]))
            if part == SCREWS:
                b.setToolTip("Screws, nuts and compression sleeves (shared by both sides)")
            bl.addWidget(b)
            self.part_buttons[part] = b
        self.btn_all = QPushButton("Generate all parts (both sides)")
        self.btn_all.clicked.connect(self.generate_all)
        bl.addWidget(self.btn_all)
        self.btn_params = QPushButton("Design parameters...")
        self.btn_params.clicked.connect(self.edit_params)
        bl.addWidget(self.btn_params)
        self.btn_clear = QPushButton("Remove generated parts")
        self.btn_clear.clicked.connect(self.clear_generated)
        bl.addWidget(self.btn_clear)
        lay.addWidget(box)

        disp = QGroupBox("Display")
        fl = QFormLayout(disp)
        self.explode = QSlider(Qt.Horizontal)
        self.explode.setRange(0, 100)
        self.explode.valueChanged.connect(lambda v: self._cam(lambda s: s.set_explode(v / 25.0)))
        fl.addRow("Explode", self.explode)
        self.pcba_opacity = QSlider(Qt.Horizontal)
        self.pcba_opacity.setRange(5, 100)
        self.pcba_opacity.setValue(100)
        self.pcba_opacity.valueChanged.connect(
            lambda v: self._cam(lambda s: s.set_group_opacity("model", v / 100.0)))
        fl.addRow("PCBA opacity", self.pcba_opacity)
        self.gen_opacity = QSlider(Qt.Horizontal)
        self.gen_opacity.setRange(5, 100)
        self.gen_opacity.setValue(100)
        self.gen_opacity.valueChanged.connect(
            lambda v: self._cam(lambda s: s.set_group_opacity("generated", v / 100.0)))
        fl.addRow("Parts opacity", self.gen_opacity)
        lay.addWidget(disp)

        lay.addWidget(QLabel("Report"))
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        lay.addWidget(self.report, 1)

        dock = QDockWidget("SCB Designer", self)
        dock.setObjectName("designDock")
        dock.setWidget(w)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    # ---------------------------------------------------------------- helpers
    def _cam(self, fn):
        fn(self.scene)
        self.viewer.refresh()

    def set_view(self, name: str):
        if name == "fit":
            self._cam(lambda s: s.fit())
        else:
            self._cam(lambda s: s.set_view(name))

    def toggle_parallel(self, on: bool):
        self._cam(lambda s: s.set_parallel(on))

    def _update_enabled(self):
        loaded = bool(self.project.raw_parts)
        design = self.project.can_design and self._busy == 0
        for b in list(self.part_buttons.values()) + [self.btn_all, self.btn_clear]:
            b.setEnabled(design)
        has_gen = bool(self.project.generated)
        self.act_export_sel.setEnabled(has_gen)
        self.act_export_each.setEnabled(has_gen)
        self.act_shot.setEnabled(loaded)
        self.act_open.setEnabled(self._busy == 0)
        self.act_demo.setEnabled(self._busy == 0)

    def _run(self, message: str, fn, done, *, fail=None):
        """Run ``fn`` in a worker thread; call ``done(result)`` in the GUI thread."""
        thread = QThread(self)
        worker = _Worker(fn)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def finish():
            self._busy -= 1
            if self._busy == 0:
                self.progress.hide()
                QApplication.restoreOverrideCursor()
            thread.quit()
            self._update_enabled()

        def ok(res):
            finish()
            done(res)

        def bad(msg):
            finish()
            self.statusBar().showMessage("Failed: " + msg)
            (fail or (lambda m: QMessageBox.critical(self, APP_NAME, m)))(msg)

        worker.finished.connect(lambda res: self._dispatch.emit(ok, res), Qt.DirectConnection)
        worker.failed.connect(lambda msg: self._dispatch.emit(bad, msg), Qt.DirectConnection)
        thread.finished.connect(lambda: self._threads.remove((thread, worker)))
        self._threads.append((thread, worker))
        if self._busy == 0:
            QApplication.setOverrideCursor(Qt.BusyCursor)
        self._busy += 1
        self.progress.show()
        self.statusBar().showMessage(message)
        self._update_enabled()
        thread.start()

    def _on_dispatch(self, fn, arg):
        fn(arg)

    @property
    def busy(self) -> bool:
        return self._busy > 0

    # ---------------------------------------------------------------- loading
    def open_dialog(self):
        settings = QSettings("SCB", APP_NAME)
        start = settings.value("lastDir", os.path.expanduser("~"))
        path, _ = QFileDialog.getOpenFileName(self, "Open STEP file", start,
                                              "STEP files (*.step *.stp *.STEP *.STP);;All files (*)")
        if path:
            settings.setValue("lastDir", os.path.dirname(path))
            self.load(path)

    def load_demo(self):
        path = default_demo_path()
        if not os.path.isfile(path):
            QMessageBox.critical(self, APP_NAME, f"Demo file not found:\n{path}")
            return
        self.load(path)

    def load(self, path: str):
        project = Project(self.project.params)

        def work():
            project.load(path)
            return _tessellate(project.display_parts)

        def done(meshes):
            self.project = project
            self.scene.clear()
            self._clear_tree(self.tree_root_model)
            self._clear_tree(self.tree_root_gen)
            for i, (part, pd) in enumerate(meshes):
                key = f"model:{i}"
                self.scene.add_part(key, part, "model", self.pcba_opacity.value() / 100.0, polydata=pd)
                self._add_tree_item(self.tree_root_model, part.name, key)
            self.tree_root_model.setText(0, f"{project.name} ({len(meshes)} parts)")
            self.tree_root_model.setExpanded(False)
            self.scene.set_view("iso")
            self.viewer.refresh()
            self.setWindowTitle(f"{APP_NAME} {__version__} - {project.name}")
            if project.can_design:
                self._show_report()
                self.statusBar().showMessage(f"Loaded {path}")
            else:
                self.report.setPlainText(
                    f"{project.pcba_error}\n\nThe model can be viewed, but SCB parts can only be "
                    "generated for a PCBA (a thin board with components).")
                self.statusBar().showMessage(f"Loaded {path} (not recognised as a PCBA)")
            self._update_enabled()

        self._run(f"Loading {os.path.basename(path)} ...", work, done)

    def _show_report(self):
        try:
            self.report.setPlainText(self.project.report())
        except Exception as exc:  # layout errors are shown, not raised
            self.report.setPlainText(f"Layout failed: {exc}")

    # ---------------------------------------------------------------- tree
    def _clear_tree(self, root: QTreeWidgetItem):
        self.tree.blockSignals(True)
        root.takeChildren()
        root.setCheckState(0, Qt.Checked)
        self.tree.blockSignals(False)

    def _add_tree_item(self, parent: QTreeWidgetItem, text: str, key: str) -> QTreeWidgetItem:
        self.tree.blockSignals(True)
        item = QTreeWidgetItem([text])
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Checked)
        item.setData(0, KEY_ROLE, key)
        parent.addChild(item)
        self.tree.blockSignals(False)
        return item

    def _item_changed(self, item: QTreeWidgetItem, _col: int):
        key = item.data(0, KEY_ROLE)
        if key and key in self.scene.objects:
            self.scene.set_visible(key, item.checkState(0) == Qt.Checked)
            self.viewer.refresh()

    # ---------------------------------------------------------------- design
    def _selected_sides(self) -> List[str]:
        return self.side_combo.currentData()

    def generate(self, parts: List[str], sides: Optional[List[str]] = None):
        sides = sides or self._selected_sides()
        jobs = []
        for part in parts:
            if part == SCREWS:
                jobs.append((part, BOTH))
            else:
                jobs += [(part, s) for s in sides]
        project = self.project

        def work():
            out = []
            for part, side in jobs:
                out.append(((part, side), _tessellate(project.generate(part, side))))
            return out

        def done(results):
            for (part, side), meshes in results:
                self._show_generated(part, side, meshes)
            self._show_report()
            names = ", ".join(f"{PART_LABELS[p].lower()} ({s})" for p, s in jobs)
            self.statusBar().showMessage(f"Generated {names}")
            self.viewer.refresh()
            self._update_enabled()

        self._run("Generating " + ", ".join(PART_LABELS[p] for p in parts) + " ...", work, done)

    def generate_all(self):
        self.generate(list(PART_TYPES), list(SIDES))

    def _show_generated(self, part: str, side: str, meshes):
        prefix = f"gen:{part}:{side}:"
        for k in [k for k in self.scene.keys() if k.startswith(prefix)]:
            self.scene.remove(k)
        # tree: one node per (part, side)
        label = f"{PART_LABELS[part]}" + ("" if side == BOTH else f" - {SIDE_LABELS[side]}")
        self.tree.blockSignals(True)
        node = None
        for i in range(self.tree_root_gen.childCount()):
            c = self.tree_root_gen.child(i)
            if c.data(0, KEY_ROLE) == prefix:
                node = c
                c.takeChildren()
        if node is None:
            node = QTreeWidgetItem([label])
            node.setFlags(node.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            node.setData(0, KEY_ROLE, prefix)
            self.tree_root_gen.addChild(node)
        node.setCheckState(0, Qt.Checked)
        self.tree.blockSignals(False)
        for i, (p, pd) in enumerate(meshes):
            key = f"{prefix}{i}"
            self.scene.add_part(key, p, "generated", self.gen_opacity.value() / 100.0,
                                explode_dir=explode_direction(p), polydata=pd)
            self._add_tree_item(node, p.name, key)
        self.tree_root_gen.setExpanded(True)

    def clear_generated(self):
        self.project.generated.clear()
        for k in [k for k in self.scene.keys() if k.startswith("gen:")]:
            self.scene.remove(k)
        self._clear_tree(self.tree_root_gen)
        self.viewer.refresh()
        self._update_enabled()

    def edit_params(self):
        dlg = ParametersDialog(self.project.params, self)
        if dlg.exec() and dlg.result_params is not None:
            self._apply_params(dlg.result_params)

    def _apply_params(self, params: SCBParameters):
        try:
            self.project.set_params(params)
        except ValueError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self.clear_generated()
        if self.project.can_design:
            self._show_report()
        self.statusBar().showMessage("Parameters updated; generated parts were cleared.")

    def load_params(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load parameters", "", "JSON (*.json)")
        if path:
            try:
                self._apply_params(SCBParameters.load(path))
            except Exception as exc:
                QMessageBox.warning(self, APP_NAME, f"Could not load parameters: {exc}")

    def save_params(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save parameters", "scb_parameters.json", "JSON (*.json)")
        if path:
            self.project.params.save(path)

    # ---------------------------------------------------------------- export
    def _checked_keys(self) -> List[Tuple[str, str]]:
        keys = []
        for i in range(self.tree_root_gen.childCount()):
            node = self.tree_root_gen.child(i)
            if node.checkState(0) != Qt.Unchecked:
                _, part, side, _ = node.data(0, KEY_ROLE).split(":")
                keys.append((part, side))
        return keys

    def export_checked(self):
        keys = self._checked_keys()
        if not keys:
            QMessageBox.information(self, APP_NAME, "Tick the generated parts to export first.")
            return
        base = os.path.splitext(self.project.name)[0] or "scb"
        path, _ = QFileDialog.getSaveFileName(self, "Export STEP", f"{base}_scb_parts.step",
                                              "STEP files (*.step *.stp)")
        if path:
            self._run("Exporting ...", lambda: self.project.export(keys, path),
                      lambda p: self.statusBar().showMessage(f"Exported {p}"))

    def export_each(self):
        folder = QFileDialog.getExistingDirectory(self, "Export each part to folder")
        if folder:
            self._run("Exporting ...", lambda: self.project.export_each(folder),
                      lambda files: self.statusBar().showMessage(f"Exported {len(files)} STEP files to {folder}"))

    def save_screenshot(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save screenshot", "scb_view.png", "PNG (*.png)")
        if path:
            self.scene.screenshot(path)
            self.statusBar().showMessage(f"Saved {path}")

    # ---------------------------------------------------------------- help
    def show_help(self):
        QMessageBox.information(self, "Mouse and keys", (
            "Left drag: rotate\n"
            "Shift + left drag or middle drag: pan\n"
            "Right drag or mouse wheel: zoom\n"
            "Ctrl + left drag: spin about the view axis\n\n"
            "F: fit all    0: isometric    1-6: top/bottom/front/back/left/right\n"
            "+/-: zoom    arrow keys: pan    Ctrl+arrows: rotate    P: orthographic"))

    def show_about(self):
        QMessageBox.about(self, APP_NAME, (
            f"<b>{APP_NAME} {__version__}</b><p>STEP viewer and generator for the parts of a "
            "phase-1 Sandwich Circuit Board: alignment layer, pressing tiles, cover plate and "
            "screw grid, for either side of the PCB.</p><p>Built on OpenCASCADE, CadQuery, VTK and Qt.</p>"))

    def closeEvent(self, event):  # pragma: no cover - GUI teardown
        for thread, _ in list(self._threads):
            thread.quit()
            thread.wait(2000)
        self.viewer.close()
        super().closeEvent(event)


def _smoke_test(app: QApplication, win: MainWindow, timeout_s: int = 600) -> None:
    """Load the demo, generate the top alignment layer, exit 0 on success.

    Used by CI to check that a frozen build actually runs.
    """
    from PySide6.QtCore import QTimer

    state = {"t": 0, "stage": 0}

    def tick():
        state["t"] += 1
        if state["t"] > timeout_s * 2:
            app.exit(2)
            return
        if win.busy:
            QTimer.singleShot(500, tick)
            return
        if state["stage"] == 0:
            state["stage"] = 1
            win.load_demo()
        elif state["stage"] == 1:
            if not win.project.can_design:
                app.exit(1)
                return
            state["stage"] = 2
            win.generate(["alignment"], ["top"])
        else:
            app.exit(0 if win.project.generated else 1)
            return
        QTimer.singleShot(500, tick)

    QTimer.singleShot(500, tick)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(APP_NAME)
    win = MainWindow()
    win.show()
    if "--smoke-test" in argv:
        _smoke_test(app, win)
    files = [a for a in argv[1:] if a.lower().endswith((".step", ".stp"))]
    if files:
        win.load(files[0])
    elif "--demo" in argv:
        win.load_demo()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
