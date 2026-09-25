"""Stack layout shared by every generated part.

The layout is computed once per (PCBA, parameters) and holds every decision
that more than one part depends on: the z-levels of the stack, the screw
positions (identical on both sides), and per side the pocket list, the spring
arm plan, the tile split lines, getter pockets, the pump port and the air
channel network.  Generating a single part therefore always gives a part that
fits the others.

All per-side coordinates are *side-local*: the side's board surface is at
``z = T`` and the stack grows towards +Z.  The bottom side is obtained by
mirroring about ``z = T/2``; X and Y are unchanged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..geometry2d import (Rect, distance_to_polygon_edge, evenly_spaced,
                          minimum_spanning_tree, point_in_polygon, segment_rect)
from ..pcba import BOTTOM, PCBA, SIDES, TOP, Feature
from .params import SBCParameters

# feature handling in the pressing layer / cover
ARM = "arm"          # fully inside the alignment layer: sprung boss
RECESS = "recess"    # pokes into the pressing layer: recess + sprung boss
THROUGH = "through"  # taller than the pressing layer: cut-out + cover dome


@dataclass
class ZLevels:
    mid: float
    board: float
    align_top: float
    press_top: float
    skin_top: float
    cover_top: float


@dataclass
class Screw:
    x: float
    y: float
    interior: bool = False


@dataclass
class ArmPlan:
    feature: Feature
    kind: str                         # cantilever | bridge | metal | rigid
    boss: Rect                        # contact pad footprint
    boss_round: bool                  # draw the boss as a cylinder
    contact_z: float                  # underside of the tile above the part
    tip_z: float                      # lowest point of the boss
    slots: List[Rect] = field(default_factory=list)
    region: Optional[Rect] = None


@dataclass
class SideLayout:
    side: str
    keyed: List[Feature]              # owner components: keyed pockets
    plain: List[Feature]              # other-side leads: plain pockets
    mode: Dict[int, str]              # id(feature) -> ARM/RECESS/THROUGH
    arms: List[ArmPlan]
    metal: List[Rect]                 # metal tile regions
    split_x: List[float]
    split_y: List[float]
    getters: List[Rect]
    getter_volume: float              # mm^3
    port: Tuple[float, float]
    channels: List[Rect]
    warnings: List[str] = field(default_factory=list)

    def features(self, mode: Optional[str] = None) -> List[Feature]:
        fs = self.keyed + self.plain
        return fs if mode is None else [f for f in fs if self.mode[id(f)] == mode]


@dataclass
class StackLayout:
    pcba: PCBA
    params: SBCParameters
    outer: Tuple[float, float, float, float]
    z: ZLevels
    screws: List[Screw]
    sides: Dict[str, SideLayout]
    warnings: List[str] = field(default_factory=list)

    @property
    def thickness(self) -> float:
        return self.pcba.thickness

    def all_warnings(self) -> List[str]:
        out = list(self.warnings)
        for s in SIDES:
            out += [f"{s}: {w}" for w in self.sides[s].warnings]
        return out


# --------------------------------------------------------------------------- #
def z_levels(T: float, p: SBCParameters) -> ZLevels:
    align_top = T + p.alignment_thickness
    press_top = align_top + p.pressing_thickness
    skin_top = press_top + p.cover_skin
    return ZLevels(T / 2, T, align_top, press_top, skin_top, skin_top + p.rib_height)


def classify(f: Feature, p: SBCParameters) -> str:
    a, t = p.alignment_thickness, p.pressing_thickness
    if f.height + p.recess_gap > a + t - p.min_roof:
        return THROUGH
    if f.height + p.recess_gap > a:
        return RECESS
    return ARM


def _clear_of_features(x, y, r, feats: List[Feature], keep: float) -> bool:
    return all(f.rect.distance_to_point((x, y)) >= r + keep for f in feats)


def place_screws(pcba: PCBA, p: SBCParameters, outer) -> Tuple[List[Screw], List[str]]:
    x0, y0, x1, y1 = outer
    e = p.screw_edge_offset
    warnings: List[str] = []
    xs = evenly_spaced(x0 + e, x1 - e, p.screw_pitch)
    ys = evenly_spaced(y0 + e, y1 - e, p.screw_pitch)
    pts = {(round(x, 6), round(y0 + e, 6)) for x in xs} | {(round(x, 6), round(y1 - e, 6)) for x in xs}
    pts |= {(round(x0 + e, 6), round(y, 6)) for y in ys} | {(round(x1 - e, 6), round(y, 6)) for y in ys}
    screws = [Screw(x, y) for x, y in sorted(pts)]

    feats = pcba.features(TOP) + pcba.features(BOTTOM)
    r = p.sleeve_od / 2
    if p.interior_screws == "existing_holes":
        for h in pcba.holes:
            if h.diameter + 1e-6 < p.screw_diameter + 0.1:
                continue
            if _clear_of_features(h.x, h.y, r, feats, p.screw_keepout):
                screws.append(Screw(h.x, h.y, True))
            else:
                warnings.append(f"PCB hole at ({h.x:.1f}, {h.y:.1f}) is too close to a component for a screw")
    elif p.interior_screws == "grid":
        bx0, by0, bx1, by1 = pcba.bounds
        gx = np.arange(bx0 + p.screw_pitch, bx1 - p.screw_pitch / 3, p.screw_pitch)
        gy = np.arange(by0 + p.screw_pitch, by1 - p.screw_pitch / 3, p.screw_pitch)
        n_added = 0
        for x in gx:
            for y in gy:
                if (point_in_polygon((x, y), pcba.outline)
                        and distance_to_polygon_edge((x, y), pcba.outline) > r + 1.0
                        and _clear_of_features(x, y, r, feats, p.screw_keepout)):
                    screws.append(Screw(float(x), float(y), True))
                    n_added += 1
        if n_added:
            warnings.append(f"{n_added} interior grid screw(s): the PCB must be drilled "
                            f"{p.screw_diameter + 0.2:.1f} mm at those positions")
    return screws, warnings


# --------------------------------------------------------------------------- #
class _Obstacles:
    def __init__(self):
        self.rects: List[Rect] = []

    def add(self, r: Rect):
        self.rects.append(r)

    def hits(self, r: Rect) -> bool:
        return any(r.overlaps(o) for o in self.rects)


def _boss_for(f: Feature, p: SBCParameters) -> Tuple[Rect, bool]:
    r = f.rect
    if f.power:
        return Rect(r.cx, r.cy, 0.8 * r.length, 0.8 * r.width, r.angle), False
    if r.area >= p.large_part_area:
        return Rect(r.cx, r.cy, 0.6 * r.length, 0.6 * r.width, r.angle), False
    d = min(max(0.6 * r.width, 0.3), 1.5)
    # tip lands 0.1 mm off centre towards the datum corner (-L/2, -W/2)
    off = 0.1 / math.sqrt(2)
    cx, cy = r.to_world(-off, -off)
    return Rect(cx, cy, d, d, r.angle), True


def _cantilever(boss: Rect, direction: np.ndarray, length: float, p: SBCParameters):
    """Slots of a U-shaped cut that frees a tongue ending over ``boss``."""
    c = np.array(boss.center)
    perp = np.array([-direction[1], direction[0]])
    tip = c - direction * (boss.length / 2 + 0.5)
    anchor = c + direction * length
    s, w = p.slot_width, p.arm_width
    side_a = tip - direction * s
    slots = []
    for sgn in (-1, 1):
        o = perp * sgn * (w / 2 + s / 2)
        slots.append(segment_rect(tuple(side_a + o), tuple(anchor + o), s))
    e0 = tip - direction * s / 2 - perp * (w / 2 + s)
    e1 = tip - direction * s / 2 + perp * (w / 2 + s)
    slots.append(segment_rect(tuple(e0), tuple(e1), s))
    region = segment_rect(tuple(side_a), tuple(anchor), w + 2 * s)
    return slots, region


def _bridge(boss: Rect, along: np.ndarray, p: SBCParameters):
    c = np.array(boss.center)
    perp = np.array([-along[1], along[0]])
    u = np.array(boss.axes[0])
    # extent of the pad along ``along`` and across it
    corners = boss.corners() - c
    ext_a = float(np.abs(corners @ along).max())
    ext_p = float(np.abs(corners @ perp).max())
    half_len = ext_a + 2.0
    beam = ext_p + 0.5
    s = p.slot_width
    slots = []
    for sgn in (-1, 1):
        o = perp * sgn * (beam + s / 2)
        slots.append(segment_rect(tuple(c - along * half_len + o), tuple(c + along * half_len + o), s))
    region = segment_rect(tuple(c - along * half_len), tuple(c + along * half_len), 2 * (beam + s))
    return slots, region


def _inside_tiles(r: Rect, pcba: PCBA, inset: float) -> bool:
    return all(point_in_polygon(tuple(c), pcba.outline)
               and distance_to_polygon_edge(tuple(c), pcba.outline) >= inset
               for c in r.corners())


def plan_arms(pcba: PCBA, p: SBCParameters, z: ZLevels, feats: List[Feature], mode, screws):
    obstacles = _Obstacles()
    for s in screws:
        obstacles.add(Rect(s.x, s.y, p.sleeve_od + 1.0, p.sleeve_od + 1.0))
    for f in feats:
        if mode[id(f)] in (RECESS, THROUGH):
            obstacles.add(f.rect.expanded(0.3))
    plans: List[ArmPlan] = []
    warnings: List[str] = []
    inset = p.board_edge_clearance + p.tile_gap + 0.5
    sprung = [f for f in feats if f.owner and mode[id(f)] in (ARM, RECESS)]
    bosses = {id(f): _boss_for(f, p) for f in sprung}
    for f in sprung:
        obstacles.add(bosses[id(f)][0].expanded(0.2))
    # biggest parts first: they have the fewest options
    for f in sorted(sprung, key=lambda f: -f.rect.area):
        boss, rnd = bosses[id(f)]
        top_c = z.board + f.height
        contact = max(z.align_top, top_c + p.recess_gap) if mode[id(f)] == RECESS else z.align_top
        tip = top_c - p.preload_interference
        plan = ArmPlan(f, "rigid", boss, rnd, contact, tip)
        others = _Obstacles()
        others.rects = [o for o in obstacles.rects]
        own = boss.expanded(0.2)
        others.rects = [o for o in others.rects if o != own and not (f.rect.expanded(0.3) == o)]
        if f.power:
            plan.kind = "metal"
        else:
            u, v = f.rect.axes
            if bosses[id(f)][0].area >= p.large_part_area * 0.36 and not rnd:
                options = [("bridge", _bridge(boss, d, p)) for d in (u, v)]
            else:
                options = []
                for length in (p.arm_length, 0.75 * p.arm_length, 0.5 * p.arm_length):
                    if length < 2.0:
                        continue
                    for d in (u, -u, v, -v):
                        options.append(("cantilever", _cantilever(boss, d, length, p)))
            for kind, (slots, region) in options:
                if others.hits(region) or not _inside_tiles(region, pcba, inset):
                    continue
                plan.kind, plan.slots, plan.region = kind, slots, region
                obstacles.add(region)
                break
            else:
                warnings.append(f"No room for a spring arm over {f.name}; rigid pad used")
        plans.append(plan)
    return plans, warnings


def _split_positions(lo: float, hi: float, max_size: float,
                     blockers: List[Tuple[float, float, float]], gap: float) -> List[float]:
    """Split lines for tiles; ``blockers`` are (start, end, cost of cutting)."""
    span = hi - lo
    n = max(1, math.ceil(span / max_size - 1e-9))
    out: List[float] = []
    min_tile = 0.5 * span / n
    for k in range(1, n):
        ideal = lo + span * k / n
        window = span / n * 0.45
        prev = out[-1] if out else lo
        best, best_cost = ideal, math.inf
        for c in np.arange(ideal - window, ideal + window + 1e-9, 0.25):
            if c - prev < min_tile or hi - c < min_tile * (n - k):
                continue
            cost = abs(c - ideal) * 0.01
            for b0, b1, w in blockers:
                if b0 - gap / 2 - 0.3 < c < b1 + gap / 2 + 0.3:
                    cost += w
            if cost < best_cost:
                best, best_cost = float(c), cost
        out.append(best)
    return out


def _frame_band(outer, p: SBCParameters):
    g_in = p.gasket_offset + p.gasket_width / 2 + 0.8
    g_out = p.frame_margin - p.board_edge_clearance - 0.8
    return g_in, g_out


def place_getters(outer, p: SBCParameters, z: ZLevels, screws) -> Tuple[List[Rect], float, Tuple[float, float], List[str]]:
    """Getter pockets and the pump port in the frame band inside the gasket."""
    x0, y0, x1, y1 = outer
    g_in, g_out = _frame_band(outer, p)
    band = g_out - g_in
    depth = (z.press_top - z.mid) - p.getter_floor
    warnings: List[str] = []
    if band < 1.0 or depth <= 0:
        return [], 0.0, ((x0 + x1) / 2, y1 - (g_in + g_out) / 2), ["Frame too narrow for a getter pocket"]
    need = p.getter_volume_ml * 1000.0
    yc_b, yc_t = y0 + (g_in + g_out) / 2, y1 - (g_in + g_out) / 2
    xc_l, xc_r = x0 + (g_in + g_out) / 2, x1 - (g_in + g_out) / 2
    # usable straight runs of the band, avoiding the corners and the port
    runs = [((x0 + g_out + 1.0, yc_b), (x1 - g_out - 1.0, yc_b)),   # bottom
            ((x0 + g_out + 1.0, yc_t), (x1 - g_out - 1.0, yc_t)),   # top
            ((xc_l, y0 + g_out + 1.0), (xc_l, y1 - g_out - 1.0)),   # left
            ((xc_r, y0 + g_out + 1.0), (xc_r, y1 - g_out - 1.0))]   # right
    port = ((x0 + x1) / 2, yc_t)
    getters: List[Rect] = []
    vol = 0.0
    for i, (a, b) in enumerate(runs):
        if vol >= need - 1e-6:
            break
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if i == 1:  # the port sits in the middle of the top run: use a half
            length = length / 2 - 3.0
            b = (port[0] - 3.0, a[1])
        if length <= 2.0:
            continue
        want = min(length, (need - vol) / (band * depth))
        want = max(want, 2.0)
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        if i < 2:
            r = Rect(mx, my, want, band, 0.0)
        else:
            r = Rect(mx, my, want, band, 90.0)
        getters.append(r)
        vol += want * band * depth
    if vol + 1e-6 < need:
        warnings.append(f"Getter volume {vol / 1000:.2f} mL < requested {p.getter_volume_ml:.2f} mL")
    return getters, vol, port, warnings


def plan_channels(nodes: List[Tuple[float, float]], p: SBCParameters, screws) -> List[Rect]:
    holes = [Rect(s.x, s.y, p.sleeve_od + 1.0, p.sleeve_od + 1.0) for s in screws if s.interior]

    def blocked(i, j):
        r = segment_rect(nodes[i], nodes[j], p.channel_width)
        return any(r.overlaps(h) for h in holes)

    edges = minimum_spanning_tree(nodes, blocked)
    return [segment_rect(nodes[i], nodes[j], p.channel_width) for i, j in edges]


def plan_side(pcba: PCBA, p: SBCParameters, z: ZLevels, outer, screws, side: str) -> SideLayout:
    feats = pcba.features(side)
    keyed = [f for f in feats if f.owner]
    plain = [f for f in feats if not f.owner]
    mode = {id(f): classify(f, p) for f in feats}
    warnings: List[str] = []

    arms, w = plan_arms(pcba, p, z, feats, mode, screws)
    warnings += w
    metal = [a.feature.rect.expanded(p.metal_tile_margin) for a in arms if a.kind == "metal"]

    # tile split lines avoid pockets, arms, metal tiles and sleeves
    bx0, by0, bx1, by1 = pcba.bounds
    blockers_x, blockers_y = [], []
    # cutting through a pocket is harmless, through an arm or a sleeve is bad,
    # through a metal tile is never wanted
    rects = [(f.rect.expanded(0.3), 0.2) for f in feats]
    rects += [(a.boss.expanded(0.5), 10.0) for a in arms]
    rects += [(a.region, 10.0) for a in arms if a.region]
    rects += [(m, 100.0) for m in metal]
    rects += [(Rect(s.x, s.y, p.sleeve_od + 1, p.sleeve_od + 1), 20.0) for s in screws if s.interior]
    for r, w in rects:
        rx0, ry0, rx1, ry1 = r.bounds()
        blockers_x.append((rx0, rx1, w))
        blockers_y.append((ry0, ry1, w))
    split_x = _split_positions(bx0, bx1, p.tile_max_size, blockers_x, p.tile_gap)
    split_y = _split_positions(by0, by1, p.tile_max_size, blockers_y, p.tile_gap)

    getters, gvol, port, w = place_getters(outer, p, z, screws)
    warnings += w
    nodes = [f.rect.center for f in keyed] + [g.center for g in getters] + [port]
    channels = plan_channels(nodes, p, screws) if len(nodes) > 1 else []

    for f in feats:
        if mode[id(f)] == THROUGH:
            warnings.append(f"{f.name} ({f.height:.1f} mm) is taller than the pressing layer; "
                            f"the cover gets a sealed dome over it")
    return SideLayout(side, keyed, plain, mode, arms, metal, split_x, split_y,
                      getters, gvol, port, channels, warnings)


def compute_layout(pcba: PCBA, params: Optional[SBCParameters] = None) -> StackLayout:
    p = params or SBCParameters()
    p.validate()
    bx0, by0, bx1, by1 = pcba.bounds
    m = p.frame_margin
    outer = (bx0 - m, by0 - m, bx1 + m, by1 + m)
    z = z_levels(pcba.thickness, p)
    screws, warnings = place_screws(pcba, p, outer)
    sides = {s: plan_side(pcba, p, z, outer, screws, s) for s in SIDES}
    return StackLayout(pcba, p, outer, z, screws, sides, warnings)
