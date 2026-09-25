"""Primitive solid builders on top of CadQuery/OpenCASCADE."""

from __future__ import annotations

from typing import Iterable, List, Sequence

import cadquery as cq

from ..geometry2d import Rect


def rect_prism(r: Rect, z0: float, z1: float) -> cq.Solid:
    h = z1 - z0
    s = cq.Solid.makeBox(r.length, r.width, h, cq.Vector(-r.length / 2, -r.width / 2, 0))
    if r.angle:
        s = s.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), r.angle)
    return s.translate(cq.Vector(r.cx, r.cy, z0))


def _rect_wire(r: Rect, z: float) -> cq.Wire:
    return cq.Wire.makePolygon([cq.Vector(x, y, z) for x, y in r.corners()], close=True)


def frustum(r0: Rect, r1: Rect, z0: float, z1: float) -> cq.Solid:
    """Loft between two rectangles (used for chamfered lead-ins)."""
    return cq.Solid.makeLoft([_rect_wire(r0, z0), _rect_wire(r1, z1)], True)


def cylinder(x: float, y: float, d: float, z0: float, z1: float) -> cq.Solid:
    return cq.Solid.makeCylinder(d / 2, z1 - z0, cq.Vector(x, y, z0))


def hex_prism(x: float, y: float, across_flats: float, z0: float, z1: float) -> cq.Solid:
    wp = cq.Workplane("XY").polygon(6, across_flats / 0.8660254).extrude(z1 - z0)
    return wp.val().translate(cq.Vector(x, y, z0))


def rounded_box(x0, y0, x1, y1, z0, z1, radius=0.0) -> cq.Solid:
    wp = cq.Workplane("XY").rect(x1 - x0, y1 - y0).extrude(z1 - z0)
    if radius > 0:
        wp = wp.edges("|Z").fillet(min(radius, (x1 - x0) / 2 - 1e-3, (y1 - y0) / 2 - 1e-3))
    return wp.val().translate(cq.Vector((x0 + x1) / 2, (y0 + y1) / 2, z0))


def outline_prism(wire: cq.Wire, offset: float, z0: float, z1: float) -> cq.Solid:
    """Extrude the board outline (at z=0), grown by ``offset``, from z0 to z1."""
    w = wire.offset2D(offset, "arc")[0] if abs(offset) > 1e-9 else wire
    face = cq.Face.makeFromWires(w)
    return cq.Solid.extrudeLinear(face, cq.Vector(0, 0, z1 - z0)).translate(cq.Vector(0, 0, z0))


def compound(shapes: Iterable[cq.Shape]) -> cq.Compound:
    return cq.Compound.makeCompound(list(shapes))


def cut(base: cq.Shape, tools: Sequence[cq.Shape]) -> cq.Shape:
    tools = [t for t in tools if t is not None]
    if not tools:
        return base
    return base.cut(*tools).clean()


def fuse(shapes: Sequence[cq.Shape]) -> cq.Shape:
    shapes = [s for s in shapes if s is not None]
    if len(shapes) == 1:
        return shapes[0]
    return shapes[0].fuse(*shapes[1:]).clean()


def intersect(a: cq.Shape, b: cq.Shape) -> cq.Shape:
    return a.intersect(b)


def mirror_to_bottom(shape: cq.Shape, board_thickness: float) -> cq.Shape:
    return shape.mirror("XY", (0, 0, board_thickness / 2))


def solids_of(shape: cq.Shape) -> List[cq.Solid]:
    return list(shape.Solids())
