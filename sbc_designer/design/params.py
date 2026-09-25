"""Design parameters for a phase-1 Sandwich Circuit Board stack.

Defaults follow the SCB project description rev. F, section 4 (alignment layer
0.75-2.7 mm, M2.5 screws on a 30 mm pitch with steel compression sleeves,
ribbed plates with a 1.2 mm skin on 5 mm ribs at 10 mm pitch, air channels to
a single port, an iron getter pocket, spring-arm pressing tiles with metal
tiles over power packages).  All lengths are millimetres.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Tuple


def _p(default, label, unit="mm", lo=None, hi=None, group="General", help=""):
    return field(default=default, metadata=dict(label=label, unit=unit, min=lo, max=hi,
                                                group=group, help=help))


@dataclass
class SBCParameters:
    # ---- alignment layer -------------------------------------------------
    alignment_thickness: float = _p(2.0, "Alignment layer thickness", lo=0.75, hi=2.7, group="Alignment layer")
    pocket_clearance: float = _p(0.15, "Pocket clearance", lo=0.0, hi=2.0, group="Alignment layer")
    lead_in: float = _p(0.3, "Chamfered lead-in", lo=0.0, hi=1.5, group="Alignment layer")
    datum_pad_width: float = _p(0.8, "Datum pad width (max)", lo=0.1, hi=5.0, group="Alignment layer")
    lead_clearance: float = _p(0.3, "Clearance round other-side leads", lo=0.0, hi=3.0, group="Alignment layer")
    channel_width: float = _p(1.5, "Air channel width", lo=0.3, hi=6.0, group="Alignment layer")
    channel_depth: float = _p(1.0, "Air channel depth", lo=0.2, hi=2.5, group="Alignment layer")
    board_edge_clearance: float = _p(0.3, "Clearance round board edge", lo=0.0, hi=3.0, group="Alignment layer")
    # ---- frame / sealing / getter ----------------------------------------
    frame_margin: float = _p(14.0, "Frame width outside the board", lo=8.0, hi=60.0, group="Frame and cavity")
    gasket_offset: float = _p(8.0, "Gasket groove offset from outer edge", lo=2.0, hi=50.0, group="Frame and cavity")
    gasket_width: float = _p(1.2, "Gasket groove width", lo=0.3, hi=5.0, group="Frame and cavity")
    gasket_depth: float = _p(0.6, "Gasket groove depth", lo=0.1, hi=3.0, group="Frame and cavity")
    getter_volume_ml: float = _p(0.7, "Getter volume (iron powder)", unit="mL", lo=0.0, hi=20.0, group="Frame and cavity",
                                 help="About 2 g of iron powder at 3 g/mL.")
    getter_floor: float = _p(0.5, "Getter pocket floor", lo=0.2, hi=3.0, group="Frame and cavity")
    port_diameter: float = _p(2.0, "Pump port bore", lo=0.5, hi=8.0, group="Frame and cavity")
    # ---- pressing layer --------------------------------------------------
    pressing_thickness: float = _p(3.0, "Pressing layer thickness", lo=1.0, hi=10.0, group="Pressing layer")
    arm_length: float = _p(6.0, "Spring arm length", lo=2.0, hi=20.0, group="Pressing layer")
    arm_width: float = _p(2.0, "Spring arm width", lo=0.5, hi=8.0, group="Pressing layer")
    slot_width: float = _p(0.5, "Arm slot width", lo=0.2, hi=2.0, group="Pressing layer")
    preload_interference: float = _p(0.1, "Tip interference (preload)", lo=0.0, hi=1.0, group="Pressing layer")
    recess_gap: float = _p(0.3, "Gap above tall components", lo=0.05, hi=3.0, group="Pressing layer")
    min_roof: float = _p(1.0, "Minimum tile roof over a recess", lo=0.3, hi=5.0, group="Pressing layer")
    large_part_area: float = _p(20.0, "Area above which a pad + bridge is used", unit="mm²", lo=1.0, hi=500.0,
                                group="Pressing layer")
    tile_max_size: float = _p(60.0, "Maximum tile size", lo=10.0, hi=500.0, group="Pressing layer")
    tile_gap: float = _p(0.4, "Gap between tiles", lo=0.1, hi=3.0, group="Pressing layer")
    metal_tile_margin: float = _p(1.5, "Metal tile margin round power package", lo=0.3, hi=10.0, group="Pressing layer")
    power_keywords: str = _p("D-PAK,DPAK,TO-252,TO-263,D2PAK,TO-220,TO-247,POWERPAK,SOT-223",
                             "Power package keywords", unit="", group="Pressing layer",
                             help="Comma separated; a component whose name contains one gets a metal tile.")
    # ---- cover plate -----------------------------------------------------
    cover_skin: float = _p(1.2, "Cover skin thickness", lo=0.5, hi=10.0, group="Cover plate")
    rib_height: float = _p(5.0, "Rib height", lo=0.0, hi=30.0, group="Cover plate")
    rib_pitch: float = _p(10.0, "Rib pitch", lo=3.0, hi=100.0, group="Cover plate")
    rib_width: float = _p(1.2, "Rib width", lo=0.4, hi=10.0, group="Cover plate")
    rim_width: float = _p(2.0, "Rim width", lo=0.5, hi=10.0, group="Cover plate")
    dome_clearance: float = _p(0.5, "Clearance round tall components", lo=0.1, hi=5.0, group="Cover plate")
    dome_wall: float = _p(1.2, "Dome wall thickness", lo=0.4, hi=5.0, group="Cover plate")
    corner_radius: float = _p(3.0, "Plate corner radius", lo=0.0, hi=20.0, group="Cover plate")
    # ---- screws ----------------------------------------------------------
    screw_pitch: float = _p(30.0, "Maximum screw pitch", lo=10.0, hi=100.0, group="Screw grid")
    screw_diameter: float = _p(2.5, "Screw diameter (M2.5)", lo=1.0, hi=6.0, group="Screw grid")
    screw_edge_offset: float = _p(4.0, "Screw line offset from outer edge", lo=2.0, hi=30.0, group="Screw grid")
    sleeve_od: float = _p(4.0, "Compression sleeve outer diameter", lo=2.0, hi=10.0, group="Screw grid")
    screw_keepout: float = _p(1.0, "Keep-out between sleeve and components", lo=0.0, hi=10.0, group="Screw grid")
    interior_screws: str = _p("existing_holes", "Interior screws", unit="", group="Screw grid",
                              help="existing_holes: use PCB holes >= screw size; grid: 30 mm grid "
                                   "(PCB must be drilled); none: perimeter only.")

    # ------------------------------------------------------------------ #
    @property
    def power_keyword_list(self) -> Tuple[str, ...]:
        return tuple(k.strip() for k in self.power_keywords.split(",") if k.strip())

    def validate(self) -> None:
        for f in dataclasses.fields(self):
            v = getattr(self, f.name)
            lo, hi = f.metadata.get("min"), f.metadata.get("max")
            if isinstance(v, (int, float)):
                if lo is not None and v < lo:
                    raise ValueError(f"{f.metadata['label']} must be >= {lo} (got {v})")
                if hi is not None and v > hi:
                    raise ValueError(f"{f.metadata['label']} must be <= {hi} (got {v})")
        if self.channel_depth >= self.alignment_thickness:
            raise ValueError("Air channel depth must be less than the alignment layer thickness")
        if self.interior_screws not in ("existing_holes", "grid", "none"):
            raise ValueError("Interior screws must be 'existing_holes', 'grid' or 'none'")
        if self.gasket_offset + self.gasket_width / 2 >= self.frame_margin - self.board_edge_clearance:
            raise ValueError("Gasket groove must lie inside the frame")
        if self.screw_edge_offset + self.sleeve_od / 2 >= self.gasket_offset - self.gasket_width / 2:
            raise ValueError("Perimeter screws must lie outside the gasket groove")

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SBCParameters":
        names = {f.name: f for f in dataclasses.fields(cls)}
        kw = {}
        for k, v in d.items():
            if k in names:
                kw[k] = type(names[k].default)(v)
        return cls(**kw)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    @classmethod
    def load(cls, path: str) -> "SBCParameters":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))
