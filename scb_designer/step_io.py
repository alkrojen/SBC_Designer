"""STEP import/export.

Reading uses the OpenCASCADE XCAF document so that the product names and
colours in the file survive; every direct child of the top level assembly is
returned as one :class:`ModelPart` (sub-assemblies are flattened into a single
compound carrying the child's name). A STEP file without assembly structure is
split into its individual solids.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence, Tuple

import cadquery as cq
from OCP.BRep import BRep_Builder
from OCP.IFSelect import IFSelect_RetDone
from OCP.Quantity import Quantity_Color
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS_Compound, TopoDS_Shape
from OCP.XCAFDoc import XCAFDoc_ColorTool, XCAFDoc_ColorType, XCAFDoc_DocumentTool

Color = Tuple[float, float, float]


class StepReadError(RuntimeError):
    """Raised when a STEP file cannot be read."""


@dataclass
class ModelPart:
    """One named, optionally coloured shape of a loaded or generated model."""

    name: str
    shape: cq.Shape
    color: Optional[Color] = None
    meta: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
def _label_name(label: TDF_Label) -> str:
    attr = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
        return attr.Get().ToExtString()
    return ""


def _linear_to_srgb(v: float) -> float:
    """OCCT stores colours as linear RGB; displays and cq.Color use sRGB."""
    v = min(max(v, 0.0), 1.0)
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def _label_color(color_tool, label: TDF_Label) -> Optional[Color]:
    col = Quantity_Color()
    for ctype in (
        XCAFDoc_ColorType.XCAFDoc_ColorSurf,
        XCAFDoc_ColorType.XCAFDoc_ColorGen,
        XCAFDoc_ColorType.XCAFDoc_ColorCurv,
    ):
        if XCAFDoc_ColorTool.GetColor_s(label, ctype, col):
            return tuple(_linear_to_srgb(v) for v in (col.Red(), col.Green(), col.Blue()))
    return None


def _first_subshape_color(shape_tool, color_tool, label: TDF_Label) -> Optional[Color]:
    subs = TDF_LabelSequence()
    shape_tool.GetSubShapes_s(label, subs)
    for i in range(1, subs.Length() + 1):
        c = _label_color(color_tool, subs.Value(i))
        if c is not None:
            return c
    return None


def _make_compound(shapes: Sequence[TopoDS_Shape]) -> TopoDS_Shape:
    if len(shapes) == 1:
        return shapes[0]
    comp = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(comp)
    for s in shapes:
        builder.Add(comp, s)
    return comp


def _collect_leaves(shape_tool, color_tool, label, loc, inherited_color, out):
    """Collect located leaf shapes (with colour) below ``label``."""
    if shape_tool.IsAssembly_s(label):
        comps = TDF_LabelSequence()
        shape_tool.GetComponents_s(label, comps)
        for i in range(1, comps.Length() + 1):
            comp = comps.Value(i)
            ref = TDF_Label()
            shape_tool.GetReferredShape_s(comp, ref)
            cloc = loc.Multiplied(shape_tool.GetLocation_s(comp))
            col = (
                _label_color(color_tool, comp)
                or _label_color(color_tool, ref)
                or inherited_color
            )
            _collect_leaves(shape_tool, color_tool, ref, cloc, col, out)
    else:
        shape = shape_tool.GetShape_s(label)
        if shape.IsNull():
            return
        col = (
            _label_color(color_tool, label)
            or inherited_color
            or _first_subshape_color(shape_tool, color_tool, label)
        )
        out.append((shape.Moved(loc), col))


def _split_solids(shape: TopoDS_Shape) -> list:
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    solids = []
    while exp.More():
        solids.append(exp.Current())
        exp.Next()
    return solids


def load_step(path: str) -> list:
    """Load a STEP file and return a list of :class:`ModelPart`.

    Raises :class:`StepReadError` if the file does not exist or is not valid
    STEP.
    """
    if not os.path.isfile(path):
        raise StepReadError(f"File not found: {path}")

    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    if reader.ReadFile(path) != IFSelect_RetDone:
        raise StepReadError(f"Not a readable STEP file: {path}")
    if not reader.Transfer(doc):
        raise StepReadError(f"Could not transfer STEP data: {path}")

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())

    free = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free)

    parts: list = []
    base = os.path.splitext(os.path.basename(path))[0]

    for i in range(1, free.Length() + 1):
        root = free.Value(i)
        if shape_tool.IsAssembly_s(root):
            comps = TDF_LabelSequence()
            shape_tool.GetComponents_s(root, comps)
            for j in range(1, comps.Length() + 1):
                comp = comps.Value(j)
                ref = TDF_Label()
                shape_tool.GetReferredShape_s(comp, ref)
                name = _label_name(comp) or _label_name(ref) or f"part{len(parts) + 1}"
                col = _label_color(color_tool, comp) or _label_color(color_tool, ref)
                leaves: list = []
                _collect_leaves(
                    shape_tool, color_tool, ref, shape_tool.GetLocation_s(comp), col, leaves
                )
                if not leaves:
                    continue
                shape = _make_compound([s for s, _ in leaves])
                color = next((c for _, c in leaves if c is not None), None)
                parts.append(ModelPart(name, cq.Shape.cast(shape), color))
        else:
            shape = shape_tool.GetShape_s(root)
            if shape.IsNull():
                continue
            name = _label_name(root) or base
            col = _label_color(color_tool, root) or _first_subshape_color(
                shape_tool, color_tool, root
            )
            solids = _split_solids(shape)
            if len(solids) > 1:
                for k, s in enumerate(solids, 1):
                    parts.append(ModelPart(f"{name}_{k}", cq.Shape.cast(s), col))
            else:
                parts.append(ModelPart(name, cq.Shape.cast(shape), col))

    if not parts:
        raise StepReadError(f"No geometry found in STEP file: {path}")
    return parts


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #
def _unique(name: str, used: set) -> str:
    base = name.replace("/", "_") or "part"
    candidate, n = base, 1
    while candidate in used:
        n += 1
        candidate = f"{base}_{n}"
    used.add(candidate)
    return candidate


def export_step(parts: Iterable[ModelPart], path: str, name: str = "SCB") -> str:
    """Write ``parts`` as one STEP assembly (names and colours kept)."""
    parts = list(parts)
    if not parts:
        raise ValueError("Nothing to export")
    assy = cq.Assembly(name=name)
    used: set = set()
    for p in parts:
        color = cq.Color(*p.color) if p.color is not None else None
        assy.add(p.shape, name=_unique(p.name, used), color=color)
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    assy.export(path, exportType="STEP")
    return path
