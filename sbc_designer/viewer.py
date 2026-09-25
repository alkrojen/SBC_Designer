"""VTK scene for viewing STEP models: rotate, zoom, pan, view presets,
visibility, transparency and an exploded view.

:class:`Scene` is GUI-independent (usable off-screen, e.g. in tests or for
screenshots); :class:`ViewerWidget` embeds it in a Qt widget with the mouse
bindings

* left drag: rotate (trackball), Shift+left or middle drag: pan,
* right drag or wheel: zoom, Ctrl+left: spin about the view axis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import vtk
from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray

from .step_io import ModelPart
from .tessellate import adaptive_tolerance, mesh_shape

DEFAULT_COLOR = (0.7, 0.7, 0.72)
BACKGROUND_TOP = (0.82, 0.86, 0.92)
BACKGROUND_BOTTOM = (0.36, 0.4, 0.48)

VIEW_DIRECTIONS = {
    # name: (direction from focal point to camera, view-up)
    "iso": ((1.0, -1.0, 1.0), (0.0, 0.0, 1.0)),
    "top": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    "bottom": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    "front": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "back": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "left": ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "right": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
}


def polydata_from_mesh(vertices: np.ndarray, triangles: np.ndarray) -> vtk.vtkPolyData:
    """Build a vtkPolyData (with split normals for crisp edges) from arrays."""
    pts = vtk.vtkPoints()
    pts.SetData(numpy_to_vtk(np.ascontiguousarray(vertices, dtype=np.float64), deep=True))
    n = len(triangles)
    ca = vtk.vtkCellArray()
    offsets = np.arange(0, 3 * n + 1, 3, dtype=np.int64)
    ca.SetData(numpy_to_vtkIdTypeArray(offsets, deep=True),
               numpy_to_vtkIdTypeArray(np.ascontiguousarray(triangles, dtype=np.int64).ravel(), deep=True))
    pd = vtk.vtkPolyData()
    pd.SetPoints(pts)
    pd.SetPolys(ca)
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(pd)
    normals.SetFeatureAngle(35.0)
    normals.SplittingOn()
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOff()
    normals.Update()
    out = vtk.vtkPolyData()
    out.DeepCopy(normals.GetOutput())
    return out


def part_polydata(part: ModelPart, tolerance: Optional[float] = None) -> vtk.vtkPolyData:
    tol = tolerance if tolerance is not None else adaptive_tolerance(part.shape)
    v, t = mesh_shape(part.shape, tol)
    return polydata_from_mesh(v, t)


def explode_direction(part: ModelPart) -> Tuple[float, float, float]:
    """Exploded-view direction of a generated SBC part (from its metadata)."""
    side, layer = part.meta.get("side"), part.meta.get("layer", 0)
    if side not in ("top", "bottom"):
        return (0.0, 0.0, 0.0)
    return (0.0, 0.0, float(layer) if side == "top" else -float(layer))


@dataclass
class SceneObject:
    key: str
    part: ModelPart
    actor: vtk.vtkActor
    group: str = "model"
    explode_dir: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    visible: bool = True


class Scene:
    """Renderer + objects + camera operations."""

    def __init__(self, render_window: Optional[vtk.vtkRenderWindow] = None, offscreen: bool = False):
        self.renderer = vtk.vtkRenderer()
        self.renderer.GradientBackgroundOn()
        self.renderer.SetBackground(*BACKGROUND_BOTTOM)
        self.renderer.SetBackground2(*BACKGROUND_TOP)
        if render_window is None:
            render_window = vtk.vtkRenderWindow()
            if offscreen:
                render_window.SetOffScreenRendering(1)
            render_window.SetSize(800, 600)
        self.render_window = render_window
        self.render_window.AddRenderer(self.renderer)
        self.objects: Dict[str, SceneObject] = {}
        self.explode_factor = 0.0
        self.explode_spacing = 15.0
        light = vtk.vtkLightKit()
        light.AddLightsToRenderer(self.renderer)

    # ---------------------------------------------------------------- objects
    def add_part(self, key: str, part: ModelPart, group: str = "model", opacity: float = 1.0,
                 explode_dir=(0.0, 0.0, 0.0), polydata: Optional[vtk.vtkPolyData] = None) -> SceneObject:
        if key in self.objects:
            self.remove(key)
        pd = polydata if polydata is not None else part_polydata(part)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(pd)
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetColor(*(part.color or DEFAULT_COLOR))
        prop.SetOpacity(opacity)
        prop.SetSpecular(0.25)
        prop.SetSpecularPower(30)
        prop.SetInterpolationToPhong()
        self.renderer.AddActor(actor)
        obj = SceneObject(key, part, actor, group, tuple(explode_dir))
        self.objects[key] = obj
        self._apply_explode(obj)
        return obj

    def remove(self, key: str) -> None:
        obj = self.objects.pop(key, None)
        if obj is not None:
            self.renderer.RemoveActor(obj.actor)

    def remove_group(self, group: str) -> None:
        for k in [k for k, o in self.objects.items() if o.group == group]:
            self.remove(k)

    def clear(self) -> None:
        for k in list(self.objects):
            self.remove(k)

    def keys(self, group: Optional[str] = None) -> List[str]:
        return [k for k, o in self.objects.items() if group is None or o.group == group]

    def set_visible(self, key: str, visible: bool) -> None:
        obj = self.objects[key]
        obj.visible = visible
        obj.actor.SetVisibility(bool(visible))

    def set_opacity(self, key: str, opacity: float) -> None:
        self.objects[key].actor.GetProperty().SetOpacity(float(opacity))

    def set_group_opacity(self, group: str, opacity: float) -> None:
        for k in self.keys(group):
            self.set_opacity(k, opacity)

    # ---------------------------------------------------------------- explode
    def _apply_explode(self, obj: SceneObject) -> None:
        d = np.array(obj.explode_dir) * self.explode_factor * self.explode_spacing
        obj.actor.SetPosition(*d)

    def set_explode(self, factor: float) -> None:
        self.explode_factor = max(0.0, float(factor))
        for obj in self.objects.values():
            self._apply_explode(obj)

    # ---------------------------------------------------------------- camera
    @property
    def camera(self) -> vtk.vtkCamera:
        return self.renderer.GetActiveCamera()

    def visible_bounds(self) -> Optional[Tuple[float, ...]]:
        b = self.renderer.ComputeVisiblePropBounds()
        if b[0] > b[1]:
            return None
        return tuple(b)

    def fit(self) -> None:
        self.renderer.ResetCamera()
        self.renderer.ResetCameraClippingRange()

    def set_view(self, name: str) -> None:
        if name not in VIEW_DIRECTIONS:
            raise ValueError(f"Unknown view: {name}")
        direction, up = VIEW_DIRECTIONS[name]
        cam = self.camera
        b = self.visible_bounds()
        center = np.array([(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2]) if b else np.zeros(3)
        d = np.array(direction, dtype=float)
        d /= np.linalg.norm(d)
        cam.SetFocalPoint(*center)
        cam.SetPosition(*(center + d * 100.0))
        cam.SetViewUp(*up)
        self.fit()

    def zoom(self, factor: float) -> None:
        """factor > 1 zooms in."""
        if factor <= 0:
            raise ValueError("zoom factor must be positive")
        cam = self.camera
        if cam.GetParallelProjection():
            cam.SetParallelScale(cam.GetParallelScale() / factor)
        else:
            cam.Dolly(factor)
        self.renderer.ResetCameraClippingRange()

    def pan(self, dx: float, dy: float) -> None:
        """Move the view by fractions of the viewport (right/up positive)."""
        cam = self.camera
        fp = np.array(cam.GetFocalPoint())
        pos = np.array(cam.GetPosition())
        up = np.array(cam.GetViewUp())
        fwd = fp - pos
        dist = np.linalg.norm(fwd)
        fwd /= dist
        right = np.cross(fwd, up)
        right /= np.linalg.norm(right)
        up = np.cross(right, fwd)
        if cam.GetParallelProjection():
            h = 2 * cam.GetParallelScale()
        else:
            h = 2 * dist * np.tan(np.radians(cam.GetViewAngle() / 2))
        w, hh = self.render_window.GetSize()
        aspect = (w / hh) if hh else 1.0
        # moving the scene right/up means moving the camera left/down
        shift = -right * dx * h * aspect - up * dy * h
        cam.SetFocalPoint(*(fp + shift))
        cam.SetPosition(*(pos + shift))
        self.renderer.ResetCameraClippingRange()

    def rotate(self, azimuth: float = 0.0, elevation: float = 0.0, roll: float = 0.0) -> None:
        cam = self.camera
        cam.Azimuth(azimuth)
        cam.Elevation(elevation)
        cam.Roll(roll)
        cam.OrthogonalizeViewUp()
        self.renderer.ResetCameraClippingRange()

    def set_parallel(self, on: bool) -> None:
        self.camera.SetParallelProjection(bool(on))
        self.fit()

    # ---------------------------------------------------------------- output
    def render(self) -> None:
        self.render_window.Render()

    def screenshot(self, path: str) -> str:
        self.render()
        w2i = vtk.vtkWindowToImageFilter()
        w2i.SetInput(self.render_window)
        w2i.ReadFrontBufferOff()
        w2i.Update()
        writer = vtk.vtkPNGWriter()
        writer.SetFileName(path)
        writer.SetInputConnection(w2i.GetOutputPort())
        writer.Write()
        return path


# --------------------------------------------------------------------------- #
# Qt widget
# --------------------------------------------------------------------------- #
try:  # Qt is optional for the scene; required for the widget
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
except Exception:  # pragma: no cover - only without Qt
    QWidget = object  # type: ignore
    QVTKRenderWindowInteractor = None  # type: ignore


class _InteractorStyle(vtk.vtkInteractorStyleTrackballCamera):
    """Trackball camera with Shift+left pan and right-drag zoom."""

    def __init__(self):
        super().__init__()
        self.SetMotionFactor(8.0)


class ViewerWidget(QWidget):  # type: ignore[misc]
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.vtk_widget = QVTKRenderWindowInteractor(self)
        layout.addWidget(self.vtk_widget)
        self.scene = Scene(self.vtk_widget.GetRenderWindow())
        self.interactor = self.vtk_widget.GetRenderWindow().GetInteractor()
        self.interactor.SetInteractorStyle(_InteractorStyle())
        axes = vtk.vtkAxesActor()
        self._marker = vtk.vtkOrientationMarkerWidget()
        self._marker.SetOrientationMarker(axes)
        self._marker.SetInteractor(self.interactor)
        self._marker.SetViewport(0.0, 0.0, 0.16, 0.22)
        self._marker.SetEnabled(1)
        self._marker.InteractiveOff()
        self.interactor.Initialize()

    def refresh(self) -> None:
        self.vtk_widget.GetRenderWindow().Render()

    def closeEvent(self, event):  # pragma: no cover - GUI teardown
        self.vtk_widget.Finalize()
        super().closeEvent(event)
