"""Generation of the individual SBC phase-1 parts.

Parts per side (top / bottom of the PCB):

* ``alignment`` - alignment layer: keyed pockets with three datum pads and a
  chamfered lead-in per component, plain pockets round the other side's
  leads, air channels (minimum spanning tree) to the getter pockets and pump
  port, the perimeter frame that wraps the board edge, gasket grooves and the
  compression-sleeve holes.
* ``pressing`` - pressing layer as a mosaic of tiles: polymer tiles with a
  U-cut cantilever (small parts) or a slotted bridge (large parts) ending in a
  contact boss, recesses over parts that rise into the layer, and a metal
  (aluminium) tile with a thermal pad over every power package.
* ``cover`` - ribbed cover plate (top plate / base plate) with screw bosses,
  sealed domes over parts taller than the stack and, on each side, a pump
  port.

Shared by both sides:

* ``screws`` - the screw grid: M2.5 screws, nuts and steel compression
  sleeves.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import cadquery as cq

from ..geometry2d import Rect
from ..pcba import BOTTOM, PCBA, SIDES, TOP
from ..step_io import ModelPart, export_step
from .layout import RECESS, THROUGH, StackLayout, compute_layout
from .params import SBCParameters
from . import solids as S

ALIGNMENT = "alignment"
PRESSING = "pressing"
COVER = "cover"
SCREWS = "screws"
PART_TYPES = (ALIGNMENT, PRESSING, COVER, SCREWS)
PART_LABELS = {
    ALIGNMENT: "Alignment layer",
    PRESSING: "Pressing layer (tiles)",
    COVER: "Cover plate",
    SCREWS: "Screw grid",
}
SIDE_LABELS = {TOP: "Top", BOTTOM: "Bottom"}
BOTH = "both"

COLORS = {
    ALIGNMENT: (0.22, 0.48, 0.92),
    "polymer": (0.95, 0.62, 0.22),
    "metal": (0.78, 0.8, 0.84),
    COVER: (0.32, 0.33, 0.36),
    "screw": (0.55, 0.56, 0.6),
    "sleeve": (0.72, 0.72, 0.74),
}
# stacking order used by the viewer's exploded view
LAYER_INDEX = {ALIGNMENT: 1, PRESSING: 2, COVER: 3, SCREWS: 4}
MIN_PIECE_VOLUME = 0.5  # mm^3; smaller slivers are dropped


class SBCDesigner:
    """Generates SBC parts for one PCBA with one parameter set."""

    def __init__(self, pcba: PCBA, params: Optional[SBCParameters] = None):
        self.pcba = pcba
        self.params = params or SBCParameters()
        self.layout: StackLayout = compute_layout(pcba, self.params)

    # ------------------------------------------------------------------ #
    @property
    def warnings(self) -> List[str]:
        return self.layout.all_warnings()

    def generate(self, part: str, side: str = TOP) -> List[ModelPart]:
        if part not in PART_TYPES:
            raise ValueError(f"Unknown part type: {part}")
        if part == SCREWS:
            return self._screws()
        if side not in SIDES:
            raise ValueError(f"Unknown side: {side}")
        builder = {ALIGNMENT: self._alignment, PRESSING: self._pressing, COVER: self._cover}[part]
        out = []
        for mp in builder(side):
            if side == BOTTOM:
                mp.shape = S.mirror_to_bottom(mp.shape, self.pcba.thickness)
            mp.meta.update(part=part, side=side, layer=LAYER_INDEX[part])
            out.append(mp)
        return out

    def generate_all(self) -> Dict[Tuple[str, str], List[ModelPart]]:
        res = {}
        for side in SIDES:
            for part in (ALIGNMENT, PRESSING, COVER):
                res[(part, side)] = self.generate(part, side)
        res[(SCREWS, BOTH)] = self.generate(SCREWS)
        return res

    @staticmethod
    def export(parts: List[ModelPart], path: str) -> str:
        return export_step(parts, path, name="SBC")

    # ------------------------------------------------------------------ #
    def _sleeve_holes(self, z0: float, z1: float, interior_z0: Optional[float] = None):
        p = self.params
        tools = []
        for s in self.layout.screws:
            lo = interior_z0 if (s.interior and interior_z0 is not None) else z0
            tools.append(S.cylinder(s.x, s.y, p.sleeve_od + 0.1, lo, z1))
        return tools

    def _gasket_ring(self, z0: float, z1: float) -> cq.Shape:
        p = self.params
        x0, y0, x1, y1 = self.layout.outer
        o, w = p.gasket_offset, p.gasket_width
        r = max(p.corner_radius - o, 0.5)
        outer = S.rounded_box(x0 + o - w / 2, y0 + o - w / 2, x1 - o + w / 2, y1 - o + w / 2, z0, z1, r + w / 2)
        inner = S.rounded_box(x0 + o + w / 2, y0 + o + w / 2, x1 - o - w / 2, y1 - o - w / 2, z0 - 1, z1 + 1,
                              max(r - w / 2, 0.1))
        return outer.cut(inner)

    def _keyed_pocket(self, rect: Rect) -> cq.Shape:
        p = self.params
        z = self.layout.z
        c, li = p.pocket_clearance, p.lead_in
        top_straight = z.align_top - li
        body = S.rect_prism(rect.expanded(c), z.board - 0.2, top_straight + 1e-3)
        if c > 1e-3:
            pw_long = min(p.datum_pad_width, 0.25 * rect.length)
            pw_short = min(p.datum_pad_width, 0.4 * rect.width)
            pads = []
            for lx in (-rect.length / 4, rect.length / 4):
                cx, cy = rect.to_world(lx, -(rect.width / 2 + c / 2))
                pads.append(S.rect_prism(Rect(cx, cy, pw_long, c + 0.02, rect.angle), z.board - 0.3, top_straight))
            cx, cy = rect.to_world(-(rect.length / 2 + c / 2), 0.0)
            pads.append(S.rect_prism(Rect(cx, cy, c + 0.02, pw_short, rect.angle), z.board - 0.3, top_straight))
            body = body.cut(*pads)
        if li > 1e-3:
            lead = S.frustum(rect.expanded(c), rect.expanded(c + li), top_straight, z.align_top + 0.01)
            body = body.fuse(lead)
        return body

    # ------------------------------------------------------------------ #
    def _alignment(self, side: str) -> List[ModelPart]:
        p, L, z = self.params, self.layout, self.layout.z
        sl = L.sides[side]
        x0, y0, x1, y1 = L.outer
        wire = self.pcba.outline_wire
        base = S.rounded_box(x0, y0, x1, y1, z.mid, z.press_top, p.corner_radius)
        base = base.cut(S.outline_prism(wire, p.board_edge_clearance, z.mid - 1, z.board),
                        S.outline_prism(wire, p.board_edge_clearance, z.align_top, z.press_top + 1))
        tools = [self._keyed_pocket(f.rect) for f in sl.keyed]
        tools += [S.rect_prism(f.rect.expanded(p.lead_clearance), z.board - 0.2, z.align_top + 0.1)
                  for f in sl.plain]
        tools += [S.rect_prism(ch, z.align_top - p.channel_depth, z.press_top + 1) for ch in sl.channels]
        tools += [S.rect_prism(g, z.mid + p.getter_floor, z.press_top + 1) for g in sl.getters]
        px, py = sl.port
        tools.append(S.cylinder(px, py, p.port_diameter + 1.5, z.align_top - p.channel_depth, z.press_top + 1))
        tools += self._sleeve_holes(z.mid - 1, z.press_top + 1, interior_z0=z.board - 0.2)
        tools.append(self._gasket_ring(z.press_top - p.gasket_depth, z.press_top + 1))
        tools.append(self._gasket_ring(z.mid - 1, z.mid + p.gasket_depth))
        shape = S.cut(base, tools)
        n = len(sl.keyed)
        return [ModelPart(f"{SIDE_LABELS[side]} alignment layer ({n} keyed pockets)", shape,
                          COLORS[ALIGNMENT], {"getter_volume_mm3": sl.getter_volume})]

    # ------------------------------------------------------------------ #
    def _pressing(self, side: str) -> List[ModelPart]:
        p, L, z = self.params, self.layout, self.layout.z
        sl = L.sides[side]
        bx0, by0, bx1, by1 = self.pcba.bounds
        slab = S.outline_prism(self.pcba.outline_wire, p.board_edge_clearance - p.tile_gap,
                               z.align_top, z.press_top)
        tools = []
        tools += [S.cylinder(s.x, s.y, p.sleeve_od + 0.1, z.align_top - 1, z.press_top + 1)
                  for s in L.screws if s.interior]
        for f in sl.features(THROUGH):
            tools.append(S.rect_prism(f.rect.expanded(p.dome_clearance), z.align_top - 1, z.press_top + 1))
        for f in sl.features(RECESS):
            tools.append(S.rect_prism(f.rect.expanded(0.3), z.align_top - 1,
                                      z.board + f.height + p.recess_gap))
        for a in sl.arms:
            tools += [S.rect_prism(s, z.align_top - 1, z.press_top + 1) for s in a.slots]
        big = 10 * (bx1 - bx0 + by1 - by0)
        for x in sl.split_x:
            tools.append(S.rect_prism(Rect(x, (by0 + by1) / 2, p.tile_gap, big, 0), z.align_top - 1, z.press_top + 1))
        for y in sl.split_y:
            tools.append(S.rect_prism(Rect((bx0 + bx1) / 2, y, big, p.tile_gap, 0), z.align_top - 1, z.press_top + 1))
        cut_slab = S.cut(slab, tools)

        def boss(a):
            if a.boss_round:
                return S.cylinder(a.boss.cx, a.boss.cy, a.boss.length, a.tip_z, a.contact_z + 0.02)
            return S.rect_prism(a.boss, a.tip_z, a.contact_z + 0.02)

        metal_parts: List[ModelPart] = []
        if sl.metal:
            polymer = S.cut(cut_slab, [S.rect_prism(m.expanded(p.tile_gap / 2), z.align_top - 1, z.press_top + 1)
                                       for m in sl.metal])
            for i, (m, a) in enumerate(zip(sl.metal, [a for a in sl.arms if a.kind == "metal"]), 1):
                tile = cut_slab.intersect(S.rect_prism(m.expanded(-p.tile_gap / 2), z.align_top - 1, z.press_top + 1))
                tile = S.fuse([tile, boss(a)])
                metal_parts.append(ModelPart(
                    f"{SIDE_LABELS[side]} pressing tile M{i} (aluminium, thermal pad) over {a.feature.name}",
                    tile, COLORS["metal"], {"material": "aluminium"}))
        else:
            polymer = cut_slab
        bosses = [boss(a) for a in sl.arms if a.kind != "metal"]
        if bosses:
            polymer = S.fuse([polymer] + bosses)
        pieces = [s for s in polymer.Solids() if s.Volume() >= MIN_PIECE_VOLUME]
        pieces.sort(key=lambda s: (round(s.Center().y / 5), s.Center().x))
        out = [ModelPart(f"{SIDE_LABELS[side]} pressing tile P{i} (polymer, PEEK/PEI)", s,
                         COLORS["polymer"], {"material": "polymer"}) for i, s in enumerate(pieces, 1)]
        return out + metal_parts

    # ------------------------------------------------------------------ #
    def _cover(self, side: str) -> List[ModelPart]:
        p, L, z = self.params, self.layout, self.layout.z
        sl = L.sides[side]
        x0, y0, x1, y1 = L.outer
        r = p.corner_radius
        parts = [S.rounded_box(x0, y0, x1, y1, z.press_top, z.skin_top, r)]
        if p.rib_height > 0:
            ribs = S.rounded_box(x0, y0, x1, y1, z.skin_top - 0.01, z.cover_top, r)
            ix0, iy0, ix1, iy1 = x0 + p.rim_width, y0 + p.rim_width, x1 - p.rim_width, y1 - p.rim_width
            inner = S.rounded_box(ix0, iy0, ix1, iy1, z.skin_top - 1, z.cover_top + 1, max(r - p.rim_width, 0.1))
            cell = p.rib_pitch - p.rib_width
            if cell > 0.1:
                nx = int((x1 - x0) // p.rib_pitch) + 2
                ny = int((y1 - y0) // p.rib_pitch) + 2
                cells = (cq.Workplane("XY").rarray(p.rib_pitch, p.rib_pitch, nx, ny)
                         .rect(cell, cell).extrude(p.rib_height + 2).val()
                         .translate(cq.Vector((x0 + x1) / 2, (y0 + y1) / 2, z.skin_top - 1)))
                ribs = ribs.cut(cells.intersect(inner))
            parts.append(ribs)
        parts += [S.cylinder(s.x, s.y, p.sleeve_od + 2.4, z.skin_top - 0.01, z.cover_top) for s in L.screws]
        through = sl.features(THROUGH)
        for f in through:
            top = max(z.board + f.height + p.dome_clearance + p.dome_wall, z.skin_top + 0.5)
            parts.append(S.rect_prism(f.rect.expanded(p.dome_clearance + p.dome_wall), z.press_top, top))
        px, py = sl.port
        parts.append(S.cylinder(px, py, p.port_diameter + 3.0, z.skin_top - 0.01, z.cover_top + 2.0))
        body = S.fuse(parts)
        tools = [S.rect_prism(f.rect.expanded(p.dome_clearance), z.press_top - 1,
                              z.board + f.height + p.dome_clearance) for f in through]
        tools += self._sleeve_holes(z.press_top - 1, z.cover_top + 1)
        tools.append(S.cylinder(px, py, p.port_diameter, z.press_top - 1, z.cover_top + 3))
        shape = S.cut(body, tools)
        label = "top plate" if side == TOP else "base plate"
        return [ModelPart(f"{SIDE_LABELS[side]} cover plate ({label}, ribbed, {len(through)} domes)",
                          shape, COLORS[COVER])]

    # ------------------------------------------------------------------ #
    def _screws(self) -> List[ModelPart]:
        p, L, z = self.params, self.layout, self.layout.z
        T = self.pcba.thickness
        top, bot = z.cover_top, T - z.cover_top
        screws, nuts, sleeves = [], [], []
        nut_h = 0.8 * p.screw_diameter
        head_d, head_h = 1.8 * p.screw_diameter, p.screw_diameter
        for s in L.screws:
            screws.append(S.fuse([S.cylinder(s.x, s.y, p.screw_diameter, bot - nut_h - 1.0, top + 0.01),
                                  S.cylinder(s.x, s.y, head_d, top, top + head_h)]))
            nuts.append(S.hex_prism(s.x, s.y, 2.0 * p.screw_diameter, bot - nut_h, bot).cut(
                S.cylinder(s.x, s.y, p.screw_diameter, bot - nut_h - 1, bot + 1)))
            lo = z.board if s.interior else z.mid
            for (a, b) in ((lo, top), (T - top, T - lo)):
                sleeves.append(S.cylinder(s.x, s.y, p.sleeve_od, a, b).cut(
                    S.cylinder(s.x, s.y, p.screw_diameter + 0.2, a - 1, b + 1)))
        n = len(L.screws)
        meta = dict(part=SCREWS, side=BOTH, layer=LAYER_INDEX[SCREWS])
        d = p.screw_diameter
        return [
            ModelPart(f"Screw grid: {n} x M{d:g} screws", S.compound(screws), COLORS["screw"], dict(meta)),
            ModelPart(f"Screw grid: {n} x M{d:g} nuts", S.compound(nuts), COLORS["screw"], dict(meta)),
            ModelPart(f"Screw grid: {2 * n} steel compression sleeves", S.compound(sleeves),
                      COLORS["sleeve"], dict(meta)),
        ]
