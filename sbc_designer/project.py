"""GUI-independent application state: the loaded model, its PCBA analysis,
the design parameters and the parts generated so far."""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from .design import BOTH, PART_TYPES, SCREWS, SBCDesigner, SBCParameters
from .pcba import PCBA, SIDES, PCBAError, analyze
from .step_io import ModelPart, export_step, load_step

Key = Tuple[str, str]  # (part type, side)


class Project:
    def __init__(self, params: Optional[SBCParameters] = None):
        self.params = params or SBCParameters()
        self.path: Optional[str] = None
        self.raw_parts: List[ModelPart] = []
        self.pcba: Optional[PCBA] = None
        self.pcba_error: Optional[str] = None
        self.generated: Dict[Key, List[ModelPart]] = {}
        self._designer: Optional[SBCDesigner] = None

    # ------------------------------------------------------------------ #
    def load(self, path: str) -> None:
        parts = load_step(path)
        self.path = path
        self.raw_parts = parts
        self.generated.clear()
        self._designer = None
        try:
            self.pcba = analyze(parts, self.params.power_keyword_list)
            self.pcba_error = None
        except PCBAError as exc:
            self.pcba = None
            self.pcba_error = str(exc)

    @property
    def name(self) -> str:
        return os.path.basename(self.path) if self.path else ""

    @property
    def display_parts(self) -> List[ModelPart]:
        """Model parts to show: the canonical frame if it is a PCBA."""
        return self.pcba.parts if self.pcba is not None else self.raw_parts

    @property
    def can_design(self) -> bool:
        return self.pcba is not None

    def set_params(self, params: SBCParameters) -> None:
        params.validate()
        rebuild = self.pcba is not None and params.power_keyword_list != self.params.power_keyword_list
        self.params = params
        self._designer = None
        self.generated.clear()
        if rebuild:
            self.pcba = analyze(self.raw_parts, params.power_keyword_list)

    @property
    def designer(self) -> SBCDesigner:
        if self.pcba is None:
            raise PCBAError(self.pcba_error or "No PCBA loaded")
        if self._designer is None:
            self._designer = SBCDesigner(self.pcba, self.params)
        return self._designer

    # ------------------------------------------------------------------ #
    def generate(self, part: str, side: str) -> List[ModelPart]:
        side = BOTH if part == SCREWS else side
        parts = self.designer.generate(part, side if side != BOTH else "top")
        self.generated[(part, side)] = parts
        return parts

    def generate_all(self) -> Dict[Key, List[ModelPart]]:
        for part in PART_TYPES:
            if part == SCREWS:
                self.generate(part, BOTH)
            else:
                for side in SIDES:
                    self.generate(part, side)
        return self.generated

    def all_generated(self) -> List[ModelPart]:
        return [p for parts in self.generated.values() for p in parts]

    def export(self, keys: Optional[List[Key]], path: str) -> str:
        keys = list(self.generated) if keys is None else keys
        parts = [p for k in keys for p in self.generated.get(k, [])]
        if not parts:
            raise ValueError("No generated parts to export")
        return export_step(parts, path, name="SBC")

    def export_each(self, folder: str) -> List[str]:
        """One STEP file per generated (part, side)."""
        os.makedirs(folder, exist_ok=True)
        base = os.path.splitext(self.name)[0] or "sbc"
        out = []
        for (part, side), parts in self.generated.items():
            path = os.path.join(folder, f"{base}_{side}_{part}.step")
            export_step(parts, path, name=f"{side}_{part}")
            out.append(path)
        return out

    def report(self) -> str:
        if self.pcba is None:
            return self.pcba_error or "No model loaded."
        p, lay = self.pcba, self.designer.layout
        x0, y0, x1, y1 = p.bounds
        lines = [
            f"Board: {x1 - x0:.1f} x {y1 - y0:.1f} x {p.thickness:.2f} mm, "
            f"{len(p.holes)} holes",
            f"Components: {p.component_count('top')} on top, {p.component_count('bottom')} on bottom",
            f"Stack height: {2 * lay.z.cover_top - p.thickness:.1f} mm, "
            f"outline {lay.outer[2] - lay.outer[0]:.1f} x {lay.outer[3] - lay.outer[1]:.1f} mm",
            f"Screws: {len(lay.screws)} (interior {sum(s.interior for s in lay.screws)})",
        ]
        for side in SIDES:
            sl = lay.sides[side]
            kinds = [a.kind for a in sl.arms]
            lines.append(
                f"{side.capitalize()}: {len(sl.keyed)} keyed pockets, {len(sl.plain)} lead pockets, "
                f"{kinds.count('cantilever')} cantilevers, {kinds.count('bridge')} bridges, "
                f"{kinds.count('metal')} metal tiles, {len(sl.channels)} air channels, "
                f"getter {sl.getter_volume / 1000:.2f} mL")
        warns = lay.all_warnings()
        if warns:
            lines.append("")
            lines.append(f"Notes ({len(warns)}):")
            lines += [f"  - {w}" for w in warns]
        return "\n".join(lines)
